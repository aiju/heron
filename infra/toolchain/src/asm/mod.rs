//! The ISA-independent assembler core.
//!
//! The core handles everything that doesn't depend on the instruction set:
//! lexing, expressions, labels (including local `.labels`), directives,
//! includes, and multi-pass size relaxation. Instructions are handed to the
//! ISA's [`Encoder`], which returns 16-bit words (parcels).
//!
//! Size relaxation: an encoder may choose between a short and a long
//! encoding. In the first pass unknown symbols evaluate to 0 (optimistic,
//! so short forms get picked); whenever a statement grows it is marked
//! "sticky long" and never shrinks again, so passes always converge.
//!
//! Object files (`relocatable`, `asm -c`): each section (`.text`, `.data`,
//! `.bss`, `.section NAME`) has its own location counter starting at 0, and
//! the linker places it. A section that uses `.org` is absolute instead.
//! Addresses the linker fills in are relocations: when an encoder evaluates
//! such an operand, [`Ctx::value`] (an address used as a number) and
//! [`Ctx::target`] (a PC-relative target) return a stand-in value that
//! makes it pick a form with a 16-bit field (a 32-bit one for symbols
//! declared `.far`), and the encoder names the field with [`Ctx::fix`]. An
//! operand it doesn't fix is an error. Labels outside `.org` sections are
//! exported unless the file lists its exports with `.global` (or hides a
//! label with `.local`).
//!
//! It replaced the Python assembler (infra/asm.py before RFC 0015): draft
//! 1's programs, libraries and C compiler output assemble to the same bytes.

mod ctx;
pub mod expr;
pub mod lex;
mod object;

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

pub use ctx::Ctx;
use expr::{EvalError, Expr, mangle};
use lex::Tok;

/// A source line: (file, line number).
pub type Where = (Arc<str>, usize);

/// An error in the source.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AsmError {
    pub msg: String,
    pub at: Option<Where>,
}

impl AsmError {
    pub fn new(msg: impl Into<String>) -> AsmError {
        AsmError {
            msg: msg.into(),
            at: None,
        }
    }

    fn at(mut self, at: &Where) -> AsmError {
        if self.at.is_none() {
            self.at = Some(at.clone());
        }
        self
    }
}

impl fmt::Display for AsmError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match &self.at {
            Some((file, line)) => write!(f, "{file}:{line}: {}", self.msg),
            None => write!(f, "{}", self.msg),
        }
    }
}

impl std::error::Error for AsmError {}

/// Why loading a source failed: an error in it, or a file that can't be
/// read.
#[derive(Debug)]
pub enum Error {
    Asm(AsmError),
    Io { path: String, err: std::io::Error },
}

impl From<AsmError> for Error {
    fn from(e: AsmError) -> Self {
        Error::Asm(e)
    }
}

impl Error {
    fn at(self, at: &Where) -> Error {
        match self {
            Error::Asm(e) => Error::Asm(e.at(at)),
            e => e,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Error::Asm(e) => e.fmt(f),
            Error::Io { path, err } => write!(f, "{path}: {err}"),
        }
    }
}

/// An instruction set's side of the assembler.
pub trait Encoder: Sync {
    /// The ISA's name, as object files record it.
    fn name(&self) -> &'static str;
    /// The number of register `name` (in lower case), if it is one.
    fn register(&self, name: &str) -> Option<u32>;
    /// The size of `.word`, in bytes.
    fn word_bytes(&self) -> i64 {
        2
    }
    /// The first address past memory: nothing may be placed from there on.
    fn mem_top(&self) -> i64 {
        0x10000
    }
    /// An instruction's parcels in hex, for the listing.
    fn hex(&self, words: &[u16]) -> String {
        let w: Vec<String> = words.iter().map(|w| format!("{w:04X}")).collect();
        w.join(" ")
    }
    /// Encode one instruction (the mnemonic in lower case) as parcels.
    fn assemble(
        &self,
        mnemonic: &str,
        ops: &[Operand],
        ctx: &mut Ctx,
    ) -> Result<Vec<u16>, AsmError>;
}

/// An expression in an operand. [`Ctx::fix`] tells the operands apart by
/// identity, so an encoder that builds a new operand from an old one keeps
/// the same `Arc`.
pub type ExprRef = Arc<Expr>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reg {
    pub n: u32,
    /// The name, in lower case.
    pub name: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Size {
    Byte,
    Half,
    Word,
}

/// `[base + disp]`. base and index are registers or None, disp an
/// expression or None. The rest is only used by ISAs with richer
/// addressing (draft 1b): an optional size keyword (`byte`, `half` or
/// `word` before the bracket), the scale of the index register
/// (`[r1 + r2*4]`), and auto-increment (`[r1]+`) or auto-decrement
/// (`-[r1]`).
#[derive(Clone, Debug)]
pub struct Mem {
    pub base: Option<Reg>,
    pub disp: Option<ExprRef>,
    pub index: Option<Reg>,
    pub scale: i64,
    pub size: Option<Size>,
    pub postinc: bool,
    pub predec: bool,
}

impl Mem {
    pub fn new(base: Option<Reg>, disp: Option<ExprRef>) -> Mem {
        Mem {
            base,
            disp,
            index: None,
            scale: 1,
            size: None,
            postinc: false,
            predec: false,
        }
    }

    /// True for the plain forms: [base + disp] without the extras.
    pub fn plain(&self) -> bool {
        self.index.is_none() && self.size.is_none() && !self.postinc && !self.predec
    }
}

#[derive(Clone, Debug)]
pub enum Operand {
    Reg(Reg),
    /// `r8-r11` (SAVE and RESTORE).
    RegRange(Reg, Reg),
    /// `#expr`
    Imm(ExprRef),
    Mem(Mem),
    /// A bare expression (a branch target, an address).
    Expr(ExprRef),
    Str(Vec<u8>),
}

impl Operand {
    /// The operand's kind as a letter: R, I, M, E, or ? for the others.
    pub fn kind(&self) -> char {
        match self {
            Operand::Reg(_) => 'R',
            Operand::Imm(_) => 'I',
            Operand::Mem(_) => 'M',
            Operand::Expr(_) => 'E',
            _ => '?',
        }
    }

    /// The expression of an immediate or a bare expression.
    pub fn expr(&self) -> Option<&ExprRef> {
        match self {
            Operand::Imm(e) | Operand::Expr(e) => Some(e),
            _ => None,
        }
    }

    pub fn reg(&self) -> Option<&Reg> {
        match self {
            Operand::Reg(r) => Some(r),
            _ => None,
        }
    }
}

/// The operands' kinds, as in "RI".
pub fn kinds(ops: &[Operand]) -> String {
    ops.iter().map(Operand::kind).collect()
}

/// Stand-in for an address the linker fills in: fits 16 bits.
pub const REP_NEAR: i64 = 0x4000;
/// ... for a .far symbol: needs 32 bits.
pub const REP_FAR: i64 = 0x45678;
/// Stand-in distance to a branch target in another section.
pub const REP_PC: i64 = 0x1000;

/// What the linker adds a value to.
#[derive(Clone, Debug, PartialEq, Eq)]
enum Base {
    /// A label in a section the linker places.
    Label(String),
    /// A symbol from another file.
    Ext(String),
    /// The start of a section.
    Sec(Arc<str>),
}

/// A field the linker fills in: (address or section offset, kind, base or
/// None for an absolute value, addend).
#[derive(Clone, Debug)]
struct Fixup {
    offset: i64,
    kind: u32,
    base: Option<Base>,
    addend: i64,
}

/// Symbol values in the order they were first defined.
#[derive(Default)]
struct Symbols {
    index: HashMap<String, usize>,
    list: Vec<(String, i64)>,
}

impl Symbols {
    fn get(&self, name: &str) -> Option<i64> {
        self.index.get(name).map(|&i| self.list[i].1)
    }

    fn set(&mut self, name: &str, v: i64) {
        match self.index.get(name) {
            Some(&i) => self.list[i].1 = v,
            None => {
                self.index.insert(name.to_string(), self.list.len());
                self.list.push((name.to_string(), v));
            }
        }
    }
}

/// What evaluating an expression needs; encoders see it through [`Ctx`].
#[derive(Default)]
struct Tables {
    relocatable: bool,
    final_pass: bool,
    symbols: Symbols,
    /// label -> its section, if the linker places it
    sym_section: HashMap<String, Option<Arc<str>>>,
    /// name = relocatable expression: (value, base)
    equ_rel: HashMap<String, (i64, Base)>,
    /// every name the file defines
    defined: HashSet<String>,
    far: HashSet<String>,
}

impl Tables {
    /// Evaluate an expression in an object file: (value, base), base None
    /// for a constant.
    fn eval_rel(
        &self,
        e: &Expr,
        pc: i64,
        section: Option<&Arc<str>>,
    ) -> Result<(i64, Option<Base>), EvalError> {
        Ok(match e {
            Expr::Num(v) => (*v, None),
            Expr::Pc => (pc, section.map(|s| Base::Sec(s.clone()))),
            Expr::Sym(name) => {
                if let Some((v, b)) = self.equ_rel.get(name) {
                    return Ok((*v, Some(b.clone())));
                }
                if let Some(v) = self.symbols.get(name) {
                    return Ok(match self.sym_section.get(name) {
                        Some(Some(_)) => (0, Some(Base::Label(name.clone()))),
                        _ => (v, None),
                    });
                }
                if self.defined.contains(name) {
                    return Err(EvalError::Unresolved(name.clone()));
                }
                (0, Some(Base::Ext(name.clone())))
            }
            Expr::Un(op, x) => {
                let (v, b) = self.eval_rel(x, pc, section)?;
                if b.is_some() && *op != "+" {
                    return Err(AsmError::new(format!(
                        "can't apply {op} to an address the linker fills in"
                    ))
                    .into());
                }
                (expr::unary(op, v)?, b)
            }
            Expr::Call(f, x) => {
                let (v, b) = self.eval_rel(x, pc, section)?;
                if b.is_some() {
                    return Err(AsmError::new(format!(
                        "can't apply {} to an address the linker fills in",
                        f.name()
                    ))
                    .into());
                }
                (f.apply(v), None)
            }
            Expr::Bin(op, a, c) => {
                let (a, ba) = self.eval_rel(a, pc, section)?;
                let (c, bc) = self.eval_rel(c, pc, section)?;
                match (ba, bc) {
                    (None, None) => (expr::binary(op, a, c)?, None),
                    (ba, None) if *op == "+" || *op == "-" => (expr::binary(op, a, c)?, ba),
                    (None, bc) if *op == "+" => (expr::binary(op, a, c)?, bc),
                    (Some(ba), Some(bc)) if *op == "-" => {
                        let (sa, sc) = (self.base_section(&ba), self.base_section(&bc));
                        if sa.is_some() && sa == sc {
                            let v = expr::binary("+", a, self.base_offset(&ba))?;
                            let v = expr::binary("-", v, c)?;
                            (expr::binary("-", v, self.base_offset(&bc))?, None)
                        } else if ba == bc {
                            (expr::binary("-", a, c)?, None)
                        } else {
                            return Err(AsmError::new(
                                "can't subtract addresses in different sections",
                            )
                            .into());
                        }
                    }
                    _ => {
                        return Err(AsmError::new(format!(
                            "can't use {op} on an address the linker fills in"
                        ))
                        .into());
                    }
                }
            }
        })
    }

    fn base_section(&self, base: &Base) -> Option<Arc<str>> {
        match base {
            Base::Label(name) => self.sym_section.get(name).cloned().flatten(),
            Base::Sec(s) => Some(s.clone()),
            Base::Ext(_) => None,
        }
    }

    fn base_offset(&self, base: &Base) -> i64 {
        match base {
            Base::Label(name) => self.symbols.get(name).unwrap_or(0),
            _ => 0,
        }
    }

    /// If an operand with this base can be encoded relative to the current
    /// statement without the linker (same section, or both absolute), the
    /// offset to add to its value.
    fn direct(&self, base: Option<&Base>, section: Option<&Arc<str>>) -> Option<i64> {
        let Some(base) = base else {
            return section.is_none().then_some(0);
        };
        match section {
            Some(s) if self.base_section(base).as_ref() == Some(s) => Some(self.base_offset(base)),
            _ => None,
        }
    }

    fn is_far(&self, base: &Base) -> bool {
        match base {
            Base::Label(name) | Base::Ext(name) => self.far.contains(name),
            Base::Sec(_) => false,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Label,
    Dir,
    Insn,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Label => "label",
            Kind::Dir => "dir",
            Kind::Insn => "insn",
        }
    }
}

/// A statement: a label, a directive or an instruction.
pub struct Stmt {
    pub at: Where,
    /// The source line.
    pub text: String,
    pub kind: Kind,
    /// The directive or mnemonic, in lower case ("" for a label).
    pub name: String,
    /// A label's name, local labels qualified ("" for the others).
    pub label: String,
    pub addr: i64,
    /// An instruction's size in bytes.
    pub size: i64,
    pub words: Vec<u16>,
    /// What a directive puts in memory.
    pub data: Vec<u8>,
    dir: Option<Dir>,
    operands: Vec<Operand>,
    sticky_long: bool,
    scope: Option<String>,
    seckey: Arc<str>,
    /// The section, if the linker places it (else addr is final).
    section: Option<Arc<str>>,
    relocs: Vec<Fixup>,
    toplevel: bool,
}

impl Stmt {
    fn new(at: &Where, text: &str, kind: Kind, seckey: &Arc<str>, scope: &Option<String>) -> Stmt {
        Stmt {
            at: at.clone(),
            text: text.to_string(),
            kind,
            name: String::new(),
            label: String::new(),
            addr: 0,
            size: 0,
            words: Vec::new(),
            data: Vec::new(),
            dir: None,
            operands: Vec::new(),
            sticky_long: false,
            scope: scope.clone(),
            seckey: seckey.clone(),
            section: None,
            relocs: Vec::new(),
            toplevel: false,
        }
    }
}

const NOBITS_PREFIXES: [&str; 2] = [".bss", ".farbss"];

/// Sections that hold only zeros (no contents in the object file).
pub fn is_nobits(section: &str) -> bool {
    NOBITS_PREFIXES
        .iter()
        .any(|p| section == *p || section.strip_prefix(p).is_some_and(|r| r.starts_with('.')))
}

/// A `.byte` operand.
enum Arg {
    Str(Vec<u8>),
    Expr(Expr),
}

/// A directive, its operands parsed.
enum Dir {
    /// `name = value` or `.equ name, value`, the name qualified.
    Equ(String, Expr),
    Org(Expr),
    Align(Expr),
    /// `.space` or `.fill`: count, fill byte.
    Space(Expr, Option<Expr>),
    Byte(Vec<Arg>),
    /// `.ascii` or `.asciz`: the bytes.
    Ascii(Vec<u8>),
    /// `.word`, `.half` or `.long`: the values, and their size in bytes.
    Data(Vec<Expr>, i64),
    Title,
}

/// A path with `dir/..` taken out, as included files are named.
fn tidy(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in path.components() {
        match c {
            Component::ParentDir
                if matches!(out.components().next_back(), Some(Component::Normal(_))) =>
            {
                out.pop();
            }
            c => out.push(c),
        }
    }
    out
}

fn undefined(name: &str) -> AsmError {
    AsmError::new(format!("undefined symbol {name}"))
}

/// The result of assembling an image: memory and symbols. The statements
/// stay in the [`Assembler`].
pub struct Image {
    /// address -> byte
    pub mem: BTreeMap<i64, u8>,
    /// (name, value) in the order they were defined
    pub symbols: Vec<(String, i64)>,
}

pub struct Assembler {
    enc: &'static dyn Encoder,
    t: Tables,
    pub warnings: Vec<String>,
    stmts: Vec<Stmt>,
    /// symbol -> the statement that defines it
    owner: HashMap<String, (usize, Where)>,
    mem_top: i64,
    cur_section: Arc<str>,
    abs_sections: HashSet<Arc<str>>,
    globals: HashSet<String>,
    globals_order: Vec<String>,
    locals: HashSet<String>,
    sec_align: HashMap<Arc<str>, i64>,
}

impl Assembler {
    pub fn new(enc: &'static dyn Encoder, relocatable: bool) -> Assembler {
        Assembler {
            enc,
            t: Tables {
                relocatable,
                ..Tables::default()
            },
            warnings: Vec::new(),
            stmts: Vec::new(),
            owner: HashMap::new(),
            mem_top: enc.mem_top(),
            cur_section: Arc::from(".text"),
            abs_sections: HashSet::new(),
            globals: HashSet::new(),
            globals_order: Vec::new(),
            locals: HashSet::new(),
            sec_align: HashMap::new(),
        }
    }

    pub fn stmts(&self) -> &[Stmt] {
        &self.stmts
    }

    /// The symbols, in the order they were defined.
    pub fn symbols(&self) -> &[(String, i64)] {
        &self.t.symbols.list
    }

    // ---- parsing ---------------------------------------------------------

    /// Read a source file, or take its text. `path` names it in messages
    /// and is where `.include` looks.
    pub fn load(&mut self, path: &str, text: Option<&str>) -> Result<(), Error> {
        self.load_in(path, text, &[])
    }

    fn load_in(&mut self, path: &str, text: Option<&str>, seen: &[PathBuf]) -> Result<(), Error> {
        // a file is the same file however the path to it is written
        let id = std::fs::canonicalize(path).unwrap_or_else(|_| PathBuf::from(path));
        if seen.contains(&id) {
            return Err(AsmError::new(format!("recursive include of {path}")).into());
        }
        let mut seen = seen.to_vec();
        seen.push(id);
        let owned;
        let text = match text {
            Some(t) => t,
            None => {
                owned = std::fs::read_to_string(path).map_err(|err| Error::Io {
                    path: path.to_string(),
                    err,
                })?;
                &owned
            }
        };
        let mut scope = self.stmts.last().and_then(|s| s.scope.clone());
        let file: Arc<str> = Arc::from(path);
        for (i, raw) in text.lines().enumerate() {
            let at = (file.clone(), i + 1);
            scope = self
                .parse_line(raw, &at, scope, path, &seen)
                .map_err(|e| e.at(&at))?;
        }
        Ok(())
    }

    fn parse_line(
        &mut self,
        raw: &str,
        at: &Where,
        mut scope: Option<String>,
        path: &str,
        seen: &[PathBuf],
    ) -> Result<Option<String>, Error> {
        let all = lex::tokenize(lex::strip_comment(raw))?;
        let mut toks = &all[..];
        // labels: "name:", possibly several on one line
        while toks.len() >= 2
            && let Tok::Id(name) = &toks[0]
            && toks[1].is_op(":")
        {
            if !name.starts_with('.') {
                scope = Some(name.clone());
            }
            let mut st = Stmt::new(at, raw, Kind::Label, &self.cur_section, &scope);
            st.label = mangle(name, scope.as_deref());
            st.toplevel = !name.starts_with('.');
            self.t.defined.insert(st.label.clone());
            self.stmts.push(st);
            toks = &toks[2..];
        }
        if toks.is_empty() {
            return Ok(scope);
        }
        // "name = expr"
        if toks.len() >= 2
            && let Tok::Id(name) = &toks[0]
            && toks[1].is_op("=")
        {
            let name = mangle(name, scope.as_deref());
            let value = expr::parse(&toks[2..], scope.as_deref())?;
            self.t.defined.insert(name.clone());
            let mut st = Stmt::new(at, raw, Kind::Dir, &self.cur_section, &scope);
            st.name = ".equ".to_string();
            st.dir = Some(Dir::Equ(name, value));
            self.stmts.push(st);
            return Ok(scope);
        }
        let Tok::Id(first) = &toks[0] else {
            return Err(AsmError::new(format!(
                "expected mnemonic or directive, got '{}'",
                toks[0]
            ))
            .into());
        };
        let name = first.to_ascii_lowercase();
        let ops = lex::split_operands(&toks[1..]);
        if matches!(name.as_str(), ".text" | ".data" | ".bss" | ".section") {
            let sec = if name == ".section" {
                let bad = || AsmError::new(".section needs a name, like .section .text.main");
                let [o] = &ops[..] else {
                    return Err(bad().into());
                };
                let [Tok::Id(sec)] = &o[..] else {
                    return Err(bad().into());
                };
                sec.clone()
            } else {
                name
            };
            self.cur_section = Arc::from(sec);
            return Ok(scope);
        }
        if name == ".org" {
            self.abs_sections.insert(self.cur_section.clone());
        }
        if matches!(
            name.as_str(),
            ".global" | ".globl" | ".extern" | ".far" | ".local"
        ) {
            let mut names = Vec::new();
            for o in &ops {
                match &o[..] {
                    [Tok::Id(n)] if !n.starts_with('.') => names.push(n.clone()),
                    _ => {
                        return Err(
                            AsmError::new(format!("{name} takes a list of symbol names")).into(),
                        );
                    }
                }
            }
            for n in names {
                match name.as_str() {
                    ".global" | ".globl" => {
                        if self.globals.insert(n.clone()) {
                            self.globals_order.push(n);
                        }
                    }
                    ".far" => {
                        self.t.far.insert(n);
                    }
                    ".local" => {
                        self.locals.insert(n);
                    }
                    _ => {}
                }
            }
            return Ok(scope);
        }
        if name == ".include" {
            let (1, Some(Tok::Str(inc))) = (ops.len(), ops.first().and_then(|o| o.first())) else {
                return Err(AsmError::new(".include needs a quoted file name").into());
            };
            let inc = String::from_utf8(inc.clone())
                .map_err(|_| AsmError::new(".include: the file name isn't UTF-8"))?;
            let dir = Path::new(path).parent().unwrap_or(Path::new(""));
            let inc_path = tidy(&dir.join(inc));
            self.load_in(&inc_path.to_string_lossy(), None, seen)?;
            return Ok(match self.stmts.last() {
                Some(st) => st.scope.clone(),
                None => scope,
            });
        }
        let mut st = Stmt::new(at, raw, Kind::Dir, &self.cur_section, &scope);
        if name.starts_with('.') {
            let dir = self.parse_directive(&name, &ops, scope.as_deref())?;
            if let Dir::Equ(n, _) = &dir {
                self.t.defined.insert(n.clone());
            }
            st.dir = Some(dir);
            st.name = name;
        } else {
            st.name = name;
            st.kind = Kind::Insn;
            st.operands = ops
                .iter()
                .map(|o| self.parse_operand(o, scope.as_deref()))
                .collect::<Result<_, _>>()?;
        }
        self.stmts.push(st);
        Ok(scope)
    }

    fn parse_directive(
        &self,
        name: &str,
        ops: &[Vec<Tok>],
        scope: Option<&str>,
    ) -> Result<Dir, AsmError> {
        let err = |msg: String| Err(AsmError::new(msg));
        let expr = |o: &[Tok]| expr::parse(o, scope);
        let one = || match ops {
            [o] => expr(o),
            _ => Err(AsmError::new(format!("{name} takes one value"))),
        };
        Ok(match name {
            ".equ" => {
                let [n, v] = ops else {
                    return err(".equ needs a name and a value".into());
                };
                let [Tok::Id(n)] = &n[..] else {
                    return err(".equ needs a name and a value".into());
                };
                Dir::Equ(mangle(n, scope), expr(v)?)
            }
            ".org" => Dir::Org(one()?),
            ".align" => Dir::Align(one()?),
            ".space" | ".fill" => match ops {
                [c] => Dir::Space(expr(c)?, None),
                [c, f] => Dir::Space(expr(c)?, Some(expr(f)?)),
                _ => return err(format!("{name} needs a count and an optional fill byte")),
            },
            ".byte" => Dir::Byte(
                ops.iter()
                    .map(|o| match &o[..] {
                        [Tok::Str(s)] => Ok(Arg::Str(s.clone())),
                        o => expr(o).map(Arg::Expr),
                    })
                    .collect::<Result<_, _>>()?,
            ),
            ".ascii" | ".asciz" => {
                let mut b = Vec::new();
                for o in ops {
                    let [Tok::Str(s)] = &o[..] else {
                        return err(format!("{name} needs strings"));
                    };
                    b.extend(s);
                }
                if name == ".asciz" {
                    b.push(0);
                }
                Dir::Ascii(b)
            }
            ".word" | ".half" | ".long" => {
                let size = match name {
                    ".half" => 2,
                    ".long" => 4,
                    _ => self.enc.word_bytes(),
                };
                let mut values = Vec::new();
                for o in ops {
                    if let [Tok::Str(_)] = &o[..] {
                        return err(format!("{name} doesn't take strings"));
                    }
                    values.push(expr(o)?);
                }
                Dir::Data(values, size)
            }
            ".title" => Dir::Title,
            _ => return err(format!("unknown directive {name}")),
        })
    }

    fn reg(&self, tok: &Tok) -> Option<Reg> {
        let name = tok.id()?.to_ascii_lowercase();
        let n = self.enc.register(&name)?;
        Some(Reg { n, name })
    }

    fn parse_operand(&self, toks: &[Tok], scope: Option<&str>) -> Result<Operand, AsmError> {
        if toks.is_empty() {
            return Err(AsmError::new("empty operand"));
        }
        if toks.len() == 1
            && let Some(r) = self.reg(&toks[0])
        {
            return Ok(Operand::Reg(r));
        }
        if toks.len() == 3
            && toks[1].is_op("-")
            && let (Some(a), Some(b)) = (self.reg(&toks[0]), self.reg(&toks[2]))
        {
            return Ok(Operand::RegRange(a, b));
        }
        if toks[0].is_op("#") {
            return Ok(Operand::Imm(Arc::new(expr::parse(&toks[1..], scope)?)));
        }
        let mut t = toks;
        let mut size = None;
        if t.len() > 1
            && (t[1].is_op("[") || t[1].is_op("-"))
            && let Some(id) = t[0].id()
        {
            size = match id.to_ascii_lowercase().as_str() {
                "byte" => Some(Size::Byte),
                "half" => Some(Size::Half),
                "word" => Some(Size::Word),
                _ => None,
            };
            if size.is_some() {
                t = &t[1..];
            }
        }
        let mut predec = false;
        let mut postinc = false;
        if t.len() > 1 && t[0].is_op("-") && t[1].is_op("[") {
            predec = true;
            t = &t[1..];
        }
        if t.len() > 1 && t[t.len() - 1].is_op("+") && t[t.len() - 2].is_op("]") && t[0].is_op("[")
        {
            postinc = true;
            t = &t[..t.len() - 1];
        }
        if t[0].is_op("[") {
            if !t[t.len() - 1].is_op("]") || t.len() < 2 {
                return Err(AsmError::new("missing ']'"));
            }
            let mut m = self.parse_mem(&t[1..t.len() - 1], scope)?;
            m.size = size;
            m.predec = predec;
            m.postinc = postinc;
            if (predec || postinc) && (m.base.is_none() || m.index.is_some() || m.disp.is_some()) {
                return Err(AsmError::new(
                    "auto-increment and auto-decrement need a plain [register]",
                ));
            }
            return Ok(Operand::Mem(m));
        }
        if size.is_some() || predec {
            return Err(AsmError::new("expected [...] after the size or '-'"));
        }
        if let [Tok::Str(s)] = t {
            return Ok(Operand::Str(s.clone()));
        }
        for tok in t {
            if self.reg(tok).is_some() {
                return Err(AsmError::new(format!(
                    "unexpected register in expression: {}",
                    tok.id().unwrap_or_default()
                )));
            }
        }
        Ok(Operand::Expr(Arc::new(expr::parse(t, scope)?)))
    }

    /// The inside of [...]: terms joined by + and -, each a register,
    /// `reg*scale` (an index), or part of the displacement expression.
    fn parse_mem(&self, inner: &[Tok], scope: Option<&str>) -> Result<Mem, AsmError> {
        let mut terms: Vec<(&'static str, Vec<Tok>)> = Vec::new();
        let mut cur = Vec::new();
        let mut depth = 0i32;
        let mut sign = "+";
        for t in inner {
            if t.is_op("(") {
                depth += 1;
            } else if t.is_op(")") {
                depth -= 1;
            }
            match t {
                Tok::Op(op @ ("+" | "-")) if depth == 0 && !cur.is_empty() => {
                    terms.push((sign, std::mem::take(&mut cur)));
                    sign = op;
                }
                _ => cur.push(t.clone()),
            }
        }
        if !cur.is_empty() {
            terms.push((sign, cur));
        }
        let subtracted = || AsmError::new("a register can't be subtracted");
        let mut regs: Vec<(Reg, i64, bool)> = Vec::new();
        let mut disp: Vec<Tok> = Vec::new();
        for (sign, tt) in terms {
            let r = self.reg(&tt[0]);
            if tt.len() == 1
                && let Some(r) = r
            {
                if sign != "+" {
                    return Err(subtracted());
                }
                regs.push((r, 1, false));
                continue;
            }
            let n = tt.len();
            let scaled = if n >= 3 && r.is_some() && tt[1].is_op("*") {
                r.map(|r| (r, &tt[2..]))
            } else if n >= 3 && tt[n - 2].is_op("*") {
                self.reg(&tt[n - 1]).map(|r| (r, &tt[..n - 2]))
            } else {
                None
            };
            if let Some((r, k)) = scaled {
                if sign != "+" {
                    return Err(subtracted());
                }
                let k = expr::eval(&expr::parse(k, scope)?, &|_| None, 0).map_err(|e| match e {
                    EvalError::Unresolved(name) => undefined(&name),
                    EvalError::Asm(e) => e,
                })?;
                regs.push((r, k, true));
                continue;
            }
            for t in &tt {
                if self.reg(t).is_some() {
                    return Err(AsmError::new(format!(
                        "unexpected register in address expression: {}",
                        t.id().unwrap_or_default()
                    )));
                }
            }
            if !disp.is_empty() || sign == "-" {
                disp.push(Tok::Op(sign));
            }
            disp.extend(tt);
        }
        if regs.len() > 2 {
            return Err(AsmError::new("at most two registers in an address"));
        }
        let plain: Vec<&Reg> = regs.iter().filter(|r| !r.2).map(|r| &r.0).collect();
        let scaled: Vec<&(Reg, i64, bool)> = regs.iter().filter(|r| r.2).collect();
        if scaled.len() > 1 {
            return Err(AsmError::new("only one register can be scaled"));
        }
        let disp = if disp.is_empty() {
            None
        } else {
            Some(Arc::new(expr::parse(&disp, scope)?))
        };
        let mut m = Mem::new(None, disp);
        if let Some((r, k, _)) = scaled.first() {
            m.index = Some(r.clone());
            m.scale = *k;
            m.base = plain.first().map(|r| (*r).clone());
        } else if plain.len() == 2 {
            m.base = Some(plain[0].clone());
            m.index = Some(plain[1].clone());
        } else if let Some(r) = plain.first() {
            m.base = Some((*r).clone());
        }
        Ok(m)
    }

    // ---- passes ----------------------------------------------------------

    /// An expression's value in this pass: (value, base), base None for a
    /// constant (see [`Tables::eval_rel`]). None while it uses a symbol that
    /// isn't defined yet; in the final pass, that's an error.
    fn value(&self, i: usize, e: &Expr, pc: i64) -> Result<Option<(i64, Option<Base>)>, AsmError> {
        let r = if self.t.relocatable {
            self.t.eval_rel(e, pc, self.stmts[i].section.as_ref())
        } else {
            expr::eval(e, &|n| self.t.symbols.get(n), pc).map(|v| (v, None))
        };
        match r {
            Ok(v) => Ok(Some(v)),
            Err(EvalError::Unresolved(name)) if self.t.final_pass => Err(undefined(&name)),
            Err(EvalError::Unresolved(_)) => Ok(None),
            Err(EvalError::Asm(e)) => Err(e),
        }
    }

    /// A directive's constant operand (0 while it isn't known yet).
    fn constant(&self, i: usize, e: &Expr, pc: i64) -> Result<i64, AsmError> {
        match self.value(i, e, pc)? {
            None => Ok(0),
            Some((v, None)) => Ok(v),
            Some((_, Some(_))) => Err(AsmError::new(format!(
                "{} needs a constant, not an address the linker fills in",
                self.stmts[i].name
            ))),
        }
    }

    /// A byte-sized value, checked in the final pass.
    fn byte(&self, i: usize, e: &Expr, pc: i64) -> Result<u8, AsmError> {
        let v = self.constant(i, e, pc)?;
        if self.t.final_pass && !(-128..=255).contains(&v) {
            let name = &self.stmts[i].name;
            return Err(AsmError::new(format!("{name} value {v} out of range")));
        }
        Ok(v as u8)
    }

    fn run_directive(&mut self, i: usize, pc: i64) -> Result<i64, AsmError> {
        let dir = self.stmts[i].dir.take().expect("a directive");
        let r = self.directive(i, &dir, pc);
        self.stmts[i].dir = Some(dir);
        r
    }

    fn directive(&mut self, i: usize, dir: &Dir, pc: i64) -> Result<i64, AsmError> {
        let n = self.stmts[i].name.clone();
        self.stmts[i].data.clear();
        match dir {
            Dir::Equ(name, e) => {
                self.define(name, i)?;
                match self.value(i, e, pc)? {
                    Some((v, None)) => self.t.symbols.set(name, v),
                    Some((v, Some(base))) => {
                        self.t.equ_rel.insert(name.clone(), (v, base));
                    }
                    None => {}
                }
                Ok(pc)
            }
            Dir::Org(e) => {
                let v = self.constant(i, e, pc)?;
                if v < 0 {
                    return Err(AsmError::new(format!(".org to a negative address, {v}")));
                }
                if v < pc && self.t.final_pass {
                    let (file, line) = &self.stmts[i].at;
                    self.warnings
                        .push(format!("{file}:{line}: .org moves backwards"));
                }
                Ok(v)
            }
            Dir::Align(e) => {
                let v = self.constant(i, e, pc)?;
                if v <= 0 {
                    return Err(AsmError::new(".align needs a positive number"));
                }
                self.note_align(i, v);
                let pad = (v - pc % v) % v;
                self.stmts[i].data = vec![0; pad as usize];
                Ok(pc + pad)
            }
            Dir::Space(count, fill) => {
                let count = self.constant(i, count, pc)?;
                let fill = match fill {
                    Some(f) => self.byte(i, f, pc)?,
                    None => 0,
                };
                if !(0..=1 << 32).contains(&count) {
                    return Err(AsmError::new(format!("{n} count {count} out of range")));
                }
                self.stmts[i].data = vec![fill; count as usize];
                Ok(pc + count)
            }
            Dir::Byte(args) => {
                let mut buf = Vec::new();
                for a in args {
                    match a {
                        Arg::Str(b) => buf.extend(b),
                        Arg::Expr(e) => buf.push(self.byte(i, e, pc)?),
                    }
                }
                let len = buf.len() as i64;
                self.stmts[i].data = buf;
                Ok(pc + len)
            }
            Dir::Ascii(b) => {
                self.stmts[i].data = b.clone();
                Ok(pc + b.len() as i64)
            }
            Dir::Data(values, size) => {
                let size = *size;
                if pc % size != 0 {
                    return Err(AsmError::new(format!(
                        "{n} at an address that isn't a multiple of {size} (missing .align?)"
                    )));
                }
                let bits = 8 * size;
                self.note_align(i, size);
                let mut buf = Vec::new();
                let mut relocs = Vec::new();
                for e in values {
                    let v = match self.value(i, e, pc)? {
                        None => 0,
                        Some((v, None)) => v,
                        Some((v, Some(base))) => {
                            let kind = match size {
                                4 => crate::obj::ABS32,
                                2 => crate::obj::ABS16,
                                _ => {
                                    return Err(AsmError::new(format!(
                                        "{n} is too small for an address the linker fills in"
                                    )));
                                }
                            };
                            relocs.push(Fixup {
                                offset: pc + buf.len() as i64,
                                kind,
                                base: Some(base),
                                addend: v,
                            });
                            0
                        }
                    };
                    if self.t.final_pass && !(-(1i64 << (bits - 1))..(1i64 << bits)).contains(&v) {
                        return Err(AsmError::new(format!("{n} value {v} out of range")));
                    }
                    buf.extend_from_slice(&v.to_le_bytes()[..size as usize]);
                }
                let len = buf.len() as i64;
                self.stmts[i].data = buf;
                self.stmts[i].relocs = relocs;
                Ok(pc + len)
            }
            Dir::Title => Ok(pc),
        }
    }

    fn define(&mut self, sym: &str, i: usize) -> Result<(), AsmError> {
        match self.owner.get(sym) {
            Some((j, (file, line))) if *j != i => Err(AsmError::new(format!(
                "{sym} is already defined at {file}:{line}"
            ))),
            Some(_) => Ok(()),
            None => {
                self.owner
                    .insert(sym.to_string(), (i, self.stmts[i].at.clone()));
                Ok(())
            }
        }
    }

    fn note_align(&mut self, i: usize, n: i64) {
        if self.t.relocatable
            && let Some(s) = &self.stmts[i].section
        {
            let a = self.sec_align.entry(s.clone()).or_insert(1);
            *a = (*a).max(n);
        }
    }

    fn encode(&self, i: usize) -> Result<(Vec<u16>, ctx::Out), AsmError> {
        let st = &self.stmts[i];
        let mut c = Ctx::new(&self.t, st);
        match self.enc.assemble(&st.name, &st.operands, &mut c) {
            Ok(words) => Ok((words, c.out)),
            Err(e) => {
                // the stand-in value for a linker-filled operand didn't fit
                if !c.out.pending.is_empty() {
                    c.out.check_fixed()?;
                }
                Err(e)
            }
        }
    }

    fn step(&mut self, i: usize, mut pc: i64, changed: &mut bool) -> Result<i64, AsmError> {
        self.stmts[i].addr = pc;
        match self.stmts[i].kind {
            Kind::Label => {
                let label = self.stmts[i].label.clone();
                self.define(&label, i)?;
                if self.t.symbols.get(&label) != Some(pc) {
                    *changed = true;
                }
                self.t.symbols.set(&label, pc);
                if self.t.relocatable {
                    self.t
                        .sym_section
                        .insert(label, self.stmts[i].section.clone());
                }
            }
            Kind::Dir => {
                pc = self.run_directive(i, pc)?;
                if self.stmts[i].name == ".org" {
                    self.stmts[i].addr = pc;
                }
            }
            Kind::Insn => {
                if pc & 1 != 0 {
                    return Err(AsmError::new(
                        "instruction at odd address (missing .align 2?)",
                    ));
                }
                self.note_align(i, 2);
                let (mut words, mut out) = self.encode(i)?;
                if (words.len() as i64) * 2 < self.stmts[i].size && !self.t.final_pass {
                    // never shrink: keep the previous long form
                    self.stmts[i].sticky_long = true;
                    (words, out) = self.encode(i)?;
                }
                if self.t.final_pass {
                    out.check_fixed()?;
                    self.stmts[i].relocs = out.relocs;
                    self.warnings.extend(out.warnings);
                }
                let st = &mut self.stmts[i];
                let size = words.len() as i64 * 2;
                if size != st.size {
                    if st.size != 0 {
                        st.sticky_long = true;
                    }
                    *changed = true;
                }
                st.size = size;
                st.words = words;
                pc += size;
            }
        }
        if pc > self.mem_top && self.stmts[i].section.is_none() {
            return Err(AsmError::new("program runs past the end of memory"));
        }
        Ok(pc)
    }

    fn one_pass(&mut self) -> Result<bool, AsmError> {
        // location counter per section (one in an image)
        let mut pcs: HashMap<Option<Arc<str>>, i64> = HashMap::new();
        let mut changed = false;
        for i in 0..self.stmts.len() {
            let key = if self.t.relocatable {
                let key = self.stmts[i].seckey.clone();
                self.stmts[i].section = (!self.abs_sections.contains(&key)).then(|| key.clone());
                Some(key)
            } else {
                None
            };
            let pc = pcs.get(&key).copied().unwrap_or(0);
            let pc = self
                .step(i, pc, &mut changed)
                .map_err(|e| e.at(&self.stmts[i].at))?;
            pcs.insert(key, pc);
        }
        Ok(changed)
    }

    fn passes(&mut self) -> Result<(), AsmError> {
        let mut converged = false;
        for _ in 0..20 {
            if !self.one_pass()? {
                converged = true;
                break;
            }
        }
        if !converged {
            return Err(AsmError::new("assembly did not converge"));
        }
        self.t.final_pass = true;
        self.one_pass()?;
        Ok(())
    }

    /// Assemble into an image (an assembler made with `relocatable` false).
    pub fn assemble(&mut self) -> Result<Image, AsmError> {
        if self.t.relocatable {
            return Err(AsmError::new("use assemble_object() for an object file"));
        }
        self.passes()?;
        let mut mem = BTreeMap::new();
        for st in &self.stmts {
            match st.kind {
                Kind::Insn => {
                    for (k, w) in st.words.iter().enumerate() {
                        let a = st.addr + 2 * k as i64;
                        mem.insert(a, (w & 0xFF) as u8);
                        mem.insert(a + 1, (w >> 8) as u8);
                    }
                }
                Kind::Dir => {
                    for (k, &b) in st.data.iter().enumerate() {
                        mem.insert(st.addr + k as i64, b);
                    }
                }
                Kind::Label => {}
            }
        }
        Ok(Image {
            mem,
            symbols: self.t.symbols.list.clone(),
        })
    }

    /// The listing: one line per source line that made statements, with
    /// the address and the first parcels or bytes.
    pub fn listing(&self) -> String {
        let mut lines = Vec::new();
        let mut groups: Vec<(&Where, Vec<&Stmt>)> = Vec::new();
        for st in &self.stmts {
            match groups.last_mut() {
                Some((w, sts)) if **w == st.at => sts.push(st),
                _ => groups.push((&st.at, vec![st])),
            }
        }
        for (_, sts) in groups {
            let text = sts[sts.len() - 1].text.trim_end();
            let body = sts
                .iter()
                .find(|st| st.kind == Kind::Insn || (st.kind == Kind::Dir && !st.data.is_empty()));
            match body {
                None => lines.push(format!("{:20} {text}", "")),
                Some(st) if st.kind == Kind::Insn => {
                    let w = self.enc.hex(&st.words);
                    lines.push(format!("{:04X}  {w:<14} {text}", st.addr));
                }
                Some(st) => {
                    let b: Vec<String> =
                        st.data.iter().take(4).map(|b| format!("{b:02X}")).collect();
                    let more = if st.data.len() > 4 { " …" } else { "" };
                    lines.push(format!(
                        "{:04X}  {:<14} {text}",
                        st.addr,
                        b.join(" ") + more
                    ));
                }
            }
        }
        lines.join("\n") + "\n"
    }
}
