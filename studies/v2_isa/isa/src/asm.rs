//! The draft 2 encoder for the assembler core (infra/toolchain), from RFC
//! 0028 and isa-v2.md. A parcel is an opcode byte, first in memory, and a
//! register byte: `rd` in its high nibble, the mode's register `R` in its
//! low one. Rows 1-6 and 8-A give an operation its modes as columns;
//! one-operand instructions take the mode from the register byte.
//!
//! The syntax is draft 1b's (studies/v1_isa/isa-v1b.md), with one spelling
//! per instruction: a store is `MOV [address], rs`, and `MOV` and `CMP`
//! pick their 7-bit forms themselves, so `ST`, `MVI` and `CMPI` are only
//! labels in the map. `PUSH r1` is `MOV -[sp], r1` and `POP r1` is
//! `MOV r1, [sp]+`; `MFHI`, `MTHI`, `MFLO` and `MTLO` are the special
//! registers HI and LO's `MFSR` and `MTSR`. The disassembler prints those
//! names: the assembler takes what the disassembler prints.

use toolchain::asm::expr::Expr;
use toolchain::asm::{AsmError, Ctx, Encoder, ExprRef, Mem, Operand, Size, kinds};
use toolchain::obj::{ABS16S, ABS24H, ABS24L, ABS32, PC16, PC16H, PC24H, PC24L};

const M32: i64 = 0xFFFF_FFFF;
/// The assembler refuses to place anything from here on.
const MEM_TOP: i64 = 0x10_0000;

const COND: [&str; 15] = [
    "EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE", "RA",
];

fn err<T>(msg: impl Into<String>) -> Result<T, AsmError> {
    Err(AsmError::new(msg))
}

fn index(names: &[&str], name: &str) -> Option<i64> {
    names.iter().position(|&n| n == name).map(|i| i as i64)
}

/// r0-r15, and sp for r15.
fn register(name: &str) -> Option<u32> {
    if name == "sp" {
        return Some(15);
    }
    let n: u32 = name.strip_prefix('r')?.parse().ok()?;
    (n < 16 && format!("r{n}") == name).then_some(n)
}

fn cond_code(suffix: &str) -> Option<i64> {
    match suffix {
        "HS" => Some(2),
        "LO" => Some(3),
        "AL" => Some(14),
        s => index(&COND, s),
    }
}

/// A value as an unsigned 32-bit pattern; accepts -2^31..2^32-1.
fn norm32(v: i64) -> Result<i64, AsmError> {
    if !(-(1 << 31)..(1 << 32)).contains(&v) {
        return err(format!("value {v} doesn't fit in 32 bits"));
    }
    Ok(v & M32)
}

/// A 32-bit pattern read as signed (so 0xFFFFFF00 counts as -256).
fn as_signed(v: i64) -> i64 {
    if ((1 << 31)..(1 << 32)).contains(&v) {
        v - (1 << 32)
    } else {
        v
    }
}

/// The number of a register operand (the caller has checked the kind).
fn rn(op: &Operand) -> i64 {
    op.reg().map_or(0, |r| r.n as i64)
}

/// The expression of an immediate or bare expression (the caller has
/// checked the kind).
fn ex(op: &Operand) -> Result<&ExprRef, AsmError> {
    op.expr()
        .ok_or_else(|| AsmError::new("expected an expression"))
}

fn reg_operand(op: &Operand, what: &str) -> Result<i64, AsmError> {
    let Operand::Reg(r) = op else {
        return err(format!("expected a {what}"));
    };
    if r.n > 15 {
        return err(format!("{} can't be used here", r.name));
    }
    Ok(r.n as i64)
}

pub struct Draft2;

pub static V2: Draft2 = Draft2;

/// The encoder for an ISA named in an object file or on a command line.
pub fn encoder(name: &str) -> Option<&'static dyn Encoder> {
    (name == "v2").then_some(&V2 as &dyn Encoder)
}

impl Encoder for Draft2 {
    fn name(&self) -> &'static str {
        "v2"
    }

    fn register(&self, name: &str) -> Option<u32> {
        // pc only means something as [pc + label]
        if name == "pc" {
            Some(16)
        } else {
            register(name)
        }
    }

    fn word_bytes(&self) -> i64 {
        4
    }

    fn mem_top(&self) -> i64 {
        MEM_TOP
    }

    /// The first parcel as its two bytes in memory, opcode first; the
    /// extension parcels, which carry data, as 16-bit values.
    fn hex(&self, words: &[u16]) -> String {
        let mut out = vec![format!("{:02X} {:02X}", words[0] & 0xFF, words[0] >> 8)];
        out.extend(words[1..].iter().map(|w| format!("{w:04X}")));
        out.join(" ")
    }

    fn assemble(&self, name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
        assemble(name, ops, ctx)
    }
}

/// A parcel: the opcode byte, and the register byte's high and low
/// nibbles.
fn p(op: i64, hi: i64, lo: i64) -> u16 {
    ((op & 0xFF) | (hi & 15) << 12 | (lo & 15) << 8) as u16
}

/// A parcel with a whole register byte.
fn pb(op: i64, rb: i64) -> u16 {
    ((op & 0xFF) | (rb & 0xFF) << 8) as u16
}

fn with_ext(first: u16, ext: Vec<u16>) -> Vec<u16> {
    let mut out = vec![first];
    out.extend(ext);
    out
}

/// The rows with every mode as a column.
fn ea_row(u: &str) -> Option<i64> {
    Some(match u {
        "MOV" => 1,
        "MOVS" => 3,
        "ADD" => 4,
        "SUB" => 5,
        "CMP" => 6,
        "AND" => 8,
        "OR" => 9,
        "XOR" => 0xA,
        _ => return None,
    })
}

/// Row D, from D0.
const UNARY: [&str; 15] = [
    "NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP", "SXB", "SXH", "ZXB", "ZXH", "CLZ", "FFS",
    "POPC", "REV",
];

/// Row C: each kind of shift takes four cells from C0.
const SHIFTS: [&str; 4] = ["LSL", "LSR", "ASR", "ROR"];

/// The register-register instructions and their cells.
fn rr_op(u: &str) -> Option<i64> {
    Some(match u {
        "ADD.B4" => 0x08,
        "TMOV" => 0x09,
        "TTST" => 0x0A,
        "TADD" => 0x0B,
        "TSUB" => 0x0C,
        "TCMP" => 0x0D,
        "ADC" => 0xE0,
        "SBC" => 0xE1,
        "BIC" => 0xE2,
        "TST" => 0xE3,
        "MULU" => 0xE4,
        "MULS" => 0xE5,
        "MULA" => 0xE6,
        "DIVU" => 0xE7,
        "DIVS" => 0xE8,
        "DIVUL" => 0xE9,
        "MERGE" => 0xEE,
        _ => return None,
    })
}

/// The ones with a special-mode form too, and its cell.
fn spec_op(u: &str) -> Option<i64> {
    Some(match u {
        "BIC" => 0xEA,
        "TST" => 0xEB,
        "MULU" => 0xEC,
        "MULS" => 0xED,
        _ => return None,
    })
}

fn bytes(size: Option<Size>) -> i64 {
    match size {
        Some(Size::Byte) => 1,
        Some(Size::Half) => 2,
        Some(Size::Word) | None => 4,
    }
}

/// The value for a word, byte or half access.
fn by_size(size: i64, word: i64, byte: i64, half: i64) -> i64 {
    match size {
        1 => byte,
        2 => half,
        _ => word,
    }
}

fn fits16(v: i64) -> bool {
    (-32768..=32767).contains(&v)
}

fn fits24(v: i64) -> bool {
    (-(1 << 23)..1 << 23).contains(&v)
}

/// A mode: (M, R, extension parcels).
type Mode = (i64, i64, Vec<u16>);

/// A constant operand; `quick` allows #q and #-q.
fn imm_mode(
    ctx: &mut Ctx,
    e: &ExprRef,
    min_ext: i64,
    n_before: i64,
    quick: bool,
) -> Result<Mode, AsmError> {
    let (mut v, known) = ctx.value(e)?;
    if known {
        v = norm32(v)?;
    }
    let sv = as_signed(v);
    if min_ext == 0 && quick {
        if (0..=15).contains(&sv) {
            return Ok((1, sv, vec![]));
        }
        if (-16..=-1).contains(&sv) {
            return Ok((0xD, -sv - 1, vec![]));
        }
    }
    if min_ext <= 1 {
        if fits16(sv) {
            ctx.fix(n_before, ABS16S, Some(e), 0)?;
            return Ok((0xF, 0, vec![(v & 0xFFFF) as u16]));
        }
        if v <= 0xFFFF {
            return Ok((0xF, 1, vec![v as u16]));
        }
        if v & 0xFFFF == 0 {
            return Ok((0xF, 2, vec![(v >> 16) as u16]));
        }
    }
    ctx.fix(n_before, ABS32, Some(e), 0)?;
    Ok((0xF, 3, vec![(v & 0xFFFF) as u16, (v >> 16) as u16]))
}

/// The index parcel: register, scale, size and the low byte.
fn index_parcel(x: i64, scale: i64, size: i64, low: i64) -> Result<u16, AsmError> {
    let s = match scale {
        1 => 0,
        2 => 1,
        4 => 2,
        8 => 3,
        _ => return err("index scale must be 1, 2, 4 or 8"),
    };
    let z = by_size(size, 2, 0, 1);
    Ok((x << 12 | s << 10 | z << 8 | (low & 0xFF)) as u16)
}

/// The special mode's tables: [abs24 + x*s] (D), or [pc + d24 + x*s] (E)
/// with `pc_next` the next instruction's address.
fn table_mode(
    ctx: &mut Ctx,
    disp: Option<&ExprRef>,
    x: i64,
    scale: i64,
    size: i64,
    n_before: i64,
    pc_next: Option<i64>,
) -> Result<Mode, AsmError> {
    let (a, known) = match (disp, pc_next) {
        (None, _) => (0, true),
        (Some(d), None) => {
            let (v, known) = ctx.value(d)?;
            (if known { as_signed(norm32(v)?) } else { 0 }, known)
        }
        (Some(d), Some(next)) => {
            let (t, known) = ctx.target(d)?;
            (t - next, known)
        }
    };
    if known && !fits24(a) {
        return err(if pc_next.is_some() {
            "PC-relative table out of range (±8 MB)"
        } else {
            "a table's address must fit in 24 bits, sign-extended"
        });
    }
    match pc_next {
        None => {
            ctx.fix(n_before, ABS24H, disp, 0)?;
            ctx.fix(n_before + 1, ABS24L, disp, 0)?;
        }
        Some(next) => {
            ctx.fix(n_before, PC24H, disp, next)?;
            ctx.fix(n_before + 1, PC24L, disp, next)?;
        }
    }
    let first = index_parcel(x, scale, size, a >> 16)?;
    Ok((
        0xF,
        if pc_next.is_some() { 0xE } else { 0xD },
        vec![first, (a & 0xFFFF) as u16],
    ))
}

/// A memory operand; `r14_slot` allows mode E, `[r14 + 4R]`, which LEA
/// doesn't have.
fn mem_mode(
    ctx: &mut Ctx,
    mem: &Mem,
    min_ext: i64,
    n_before: i64,
    r14_slot: bool,
) -> Result<Mode, AsmError> {
    let size = bytes(mem.size);
    let next = ctx.pc + 2 * (n_before + 1);
    let index = match &mem.index {
        Some(r) if r.n > 15 => return err("bad index register"),
        Some(r) => Some(r.n as i64),
        None => None,
    };
    if let Some(base) = &mem.base
        && base.n == 16
    {
        // [pc + label], or [pc + table + x*s]
        if mem.postinc || mem.predec {
            return err("[pc + ...] takes a label, and an index register");
        }
        if let Some(x) = index {
            let next = ctx.pc + 2 * (n_before + 2);
            return table_mode(
                ctx,
                mem.disp.as_ref(),
                x,
                mem.scale,
                size,
                n_before,
                Some(next),
            );
        }
        let (target, known) = match &mem.disp {
            Some(d) => ctx.target(d)?,
            None => (next, true),
        };
        let off = target - next;
        if known && !fits16(off) {
            return err("PC-relative target out of range (±32 KB)");
        }
        ctx.fix(n_before, PC16, mem.disp.as_ref(), next)?;
        return Ok((
            0xF,
            by_size(size, 0xA, 0xB, 0xC),
            vec![(off & 0xFFFF) as u16],
        ));
    }
    let base_n = mem.base.as_ref().map(|r| r.n as i64);
    if mem.postinc || mem.predec {
        let b = base_n.unwrap_or(0);
        if mem.postinc {
            return match size {
                4 => Ok((6, b, vec![])),
                1 => Ok((0xA, b, vec![])),
                _ => err("there is no half [r]+ mode"),
            };
        }
        if size != 4 {
            return err("-[r] only exists for words");
        }
        return Ok((7, b, vec![]));
    }
    if let Some(x) = index {
        let Some(b) = base_n else {
            // [table + x*s]
            return table_mode(ctx, mem.disp.as_ref(), x, mem.scale, size, n_before, None);
        };
        let (d8, known) = match &mem.disp {
            Some(d) => ctx.value(d)?,
            None => (0, true),
        };
        if known && !(-128..=127).contains(&as_signed(norm32(d8)?)) {
            return err("the indexed mode's displacement must fit in 8 bits");
        }
        return Ok((5, b, vec![index_parcel(x, mem.scale, size, d8)?]));
    }
    let (mut disp, known) = match &mem.disp {
        Some(d) => ctx.value(d)?,
        None => (0, true),
    };
    if known {
        disp = norm32(disp)?;
    }
    let sd = as_signed(disp);
    let Some(b) = base_n else {
        // absolute
        if min_ext <= 1 && (!known || fits16(sd)) {
            ctx.fix(n_before, ABS16S, mem.disp.as_ref(), 0)?;
            return Ok((0xF, by_size(size, 4, 5, 6), vec![(disp & 0xFFFF) as u16]));
        }
        let off = disp - next;
        if min_ext <= 1 && known && ctx.abs_pc() && fits16(off) {
            return Ok((
                0xF,
                by_size(size, 0xA, 0xB, 0xC),
                vec![(off & 0xFFFF) as u16],
            ));
        }
        ctx.fix(n_before, ABS32, mem.disp.as_ref(), 0)?;
        return Ok((
            0xF,
            by_size(size, 7, 8, 9),
            vec![(disp & 0xFFFF) as u16, (disp >> 16) as u16],
        ));
    };
    if min_ext == 0 && known && sd == 0 {
        return Ok((by_size(size, 2, 8, 0xB), b, vec![]));
    }
    // the slot modes: the first 16 words at sp, and at r14
    let slot = min_ext == 0 && known && size == 4 && (0..=60).contains(&sd) && sd % 4 == 0;
    if slot && b == 15 {
        return Ok((4, sd / 4, vec![]));
    }
    if slot && b == 14 && r14_slot {
        return Ok((0xE, sd / 4, vec![]));
    }
    if min_ext <= 1 && (!known || fits16(sd)) {
        ctx.fix(n_before, ABS16S, mem.disp.as_ref(), 0)?;
        return Ok((by_size(size, 3, 9, 0xC), b, vec![(disp & 0xFFFF) as u16]));
    }
    // [R + d24]: the table mode with R as the index
    table_mode(ctx, mem.disp.as_ref(), b, 1, size, n_before, None)
}

/// An operand's mode; `quick` allows the quick constants.
fn ea(ctx: &mut Ctx, op: &Operand, n_before: i64, quick: bool) -> Result<Mode, AsmError> {
    let min_ext = (ctx.min_words() - n_before).max(0);
    match op {
        Operand::Reg(r) => {
            if r.n > 15 {
                return err("pc can only be used as [pc + label]");
            }
            Ok((0, r.n as i64, vec![]))
        }
        Operand::Imm(e) => imm_mode(ctx, e, min_ext, n_before, quick),
        Operand::Mem(m) => mem_mode(ctx, m, min_ext, n_before, true),
        _ => err("expected a register, #constant or [memory] operand"),
    }
}

/// A constant 16..127 for MOV's and CMP's 7-bit forms, if the operand is
/// one and the statement may be one parcel.
fn u7(ctx: &mut Ctx, op: &Operand) -> Result<Option<i64>, AsmError> {
    let Operand::Imm(e) = op else {
        return Ok(None);
    };
    if ctx.min_words() > 1 {
        return Ok(None);
    }
    let (v, known) = ctx.value(e)?;
    if !known {
        return Ok(None);
    }
    let v = as_signed(norm32(v)?);
    Ok((16..=127).contains(&v).then_some(v))
}

/// `r8-r11`, or a single register, within r0..=`top`.
fn reg_range(op: &Operand, top: i64) -> Result<(i64, i64), AsmError> {
    let (a, b) = match op {
        Operand::Reg(r) => (r.n as i64, r.n as i64),
        Operand::RegRange(a, b) => (a.n as i64, b.n as i64),
        _ => return err("expected a register range like r8-r11"),
    };
    if !(a <= b && b <= top) {
        return err(format!(
            "register range must be within r0-{}, low to high",
            if top == 15 { "sp" } else { "r14" }
        ));
    }
    Ok((a, b))
}

/// A special register: flags, hi, lo, or a number 0-15.
fn sr_number(ctx: &mut Ctx, op: &Operand) -> Result<i64, AsmError> {
    if let Operand::Expr(e) = op
        && let Expr::Sym(name) = &**e
    {
        match name.to_ascii_lowercase().as_str() {
            "flags" => return Ok(0),
            "hi" => return Ok(1),
            "lo" => return Ok(9),
            _ => {}
        }
    }
    let Some(e) = op.expr() else {
        return err("expected a special register: flags, hi, lo or a number");
    };
    let (v, _) = ctx.value(e)?;
    if !(0..=15).contains(&v) {
        return err("special register must be 0-15");
    }
    Ok(v)
}

/// Jcc, JMP (14) and CALL (15) to a label: 16 bits PC-relative, or 32
/// absolute.
fn jcc(ctx: &mut Ctx, cc: i64, e: &ExprRef) -> Result<Vec<u16>, AsmError> {
    let (target, known) = ctx.target(e)?;
    let next = ctx.pc + 4;
    let off = target - next;
    if known && off & 1 != 0 {
        return err("jump target is at an odd address");
    }
    if ctx.min_words() > 2 || (known && !(-65536..=65534).contains(&off)) {
        let (t, known) = ctx.value(e)?;
        let t = if known { norm32(t)? } else { 0 };
        ctx.fix(1, ABS32, Some(e), 0)?;
        return Ok(vec![p(0xF3, cc, 0), (t & 0xFFFF) as u16, (t >> 16) as u16]);
    }
    ctx.fix(1, PC16H, Some(e), next)?;
    Ok(vec![p(0xF2, cc, 0), ((off >> 1) & 0xFFFF) as u16])
}

fn no_operands(u: &str, ops: &[Operand]) -> Result<(), AsmError> {
    if ops.is_empty() {
        Ok(())
    } else {
        err(format!("{u} takes no operands"))
    }
}

fn two_regs(u: &str, ops: &[Operand]) -> Result<(i64, i64), AsmError> {
    if kinds(ops) != "RR" {
        return err(format!("{u} needs 'rd, rs'"));
    }
    Ok((
        reg_operand(&ops[0], "register")?,
        reg_operand(&ops[1], "register")?,
    ))
}

/// What 1b spelled differently, and how draft 2 writes it.
fn renamed(u: &str) -> Option<&'static str> {
    Some(match u {
        "ST" => "a store is written MOV [address], rs",
        "MVI" => "write MOV rd, #value",
        "CMPI" => "write CMP rd, #value",
        "LI" => "write MOV rd, #value",
        "MFF" => "write MFSR rd, flags",
        "MTF" => "write MTSR flags, rs",
        "ADDI" => "write ADD rd, #value",
        _ => return None,
    })
}

fn assemble(name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
    let u = name.to_ascii_uppercase();
    let u = u.as_str();
    let k = kinds(ops);
    let k = k.as_str();
    let one = |v: u16| Ok(vec![v]);

    match u {
        "RET" => return no_operands(u, ops).map(|_| vec![pb(0xFD, 0x00)]),
        "NOP" => return no_operands(u, ops).map(|_| vec![pb(0xFD, 0xFD)]),
        "EI" => return no_operands(u, ops).map(|_| vec![pb(0xFE, 0x00)]),
        "DI" => return no_operands(u, ops).map(|_| vec![pb(0xFE, 0x01)]),
        "RTI" => return no_operands(u, ops).map(|_| vec![pb(0xFE, 0x02)]),
        "HALT" => return no_operands(u, ops).map(|_| vec![pb(0xFE, 0x03)]),
        "SAVE" | "RESTORE" => {
            let [op] = ops else {
                return err(format!("{u} needs a register range like r8-r11"));
            };
            let (a, b) = reg_range(op, 14)?;
            return one(p(if u == "SAVE" { 0xF4 } else { 0xF5 }, a, b));
        }
        "LDM" | "STM" => {
            let [base @ Operand::Reg(_), range] = ops else {
                return err(format!("{u} needs 'rb, ra-rc'"));
            };
            let b = reg_operand(base, "register")?;
            let (a, c) = reg_range(range, 15)?;
            let op = if u == "LDM" { 0x01 } else { 0x02 };
            return Ok(vec![p(op, a, b), (c << 12) as u16]);
        }
        "MFSR" => {
            if ops.len() != 2 {
                return err("MFSR needs 'rd, n'");
            }
            let rd = reg_operand(&ops[0], "register")?;
            let n = sr_number(ctx, &ops[1])?;
            return one(p(0x0E, rd, n));
        }
        "MTSR" => {
            if ops.len() != 2 {
                return err("MTSR needs 'n, rs'");
            }
            let n = sr_number(ctx, &ops[0])?;
            let rs = reg_operand(&ops[1], "register")?;
            return one(p(0x0F, n, rs));
        }
        "PUSH" | "POP" => {
            let [r @ Operand::Reg(_)] = ops else {
                return err(format!("{u} needs one register"));
            };
            let r = reg_operand(r, "register")?;
            return one(if u == "PUSH" {
                p(0x27, r, 15)
            } else {
                p(0x16, r, 15)
            });
        }
        "MFHI" | "MFLO" | "MTHI" | "MTLO" => {
            let [r @ Operand::Reg(_)] = ops else {
                return err(format!("{u} needs one register"));
            };
            let r = reg_operand(r, "register")?;
            let n = if u.ends_with("HI") { 1 } else { 9 };
            return one(if u.starts_with("MF") {
                p(0x0E, r, n)
            } else {
                p(0x0F, n, r)
            });
        }
        "MFUR" | "MTUR" => {
            let (a, b) = two_regs(u, ops)?;
            let f = if u == "MFUR" { 0x10 } else { 0x11 };
            return Ok(vec![pb(0xFE, f), (a << 12 | b << 8) as u16]);
        }
        "SWI" => {
            let [op] = ops else {
                return err("SWI needs '#n'");
            };
            let Some(e) = op.expr() else {
                return err("SWI needs '#n'");
            };
            let (v, known) = ctx.value(e)?;
            if known && !(0..=255).contains(&v) {
                return err("SWI number must be 0-255");
            }
            return one(pb(0xFC, v));
        }
        "MULFX" => {
            let [Operand::Reg(_), Operand::Reg(_), Operand::Imm(e)] = ops else {
                return err("MULFX needs 'rd, rs, #n'");
            };
            let (d, s) = two_regs(u, &ops[..2])?;
            let (n, known) = ctx.value(e)?;
            if known && !(0..=31).contains(&n) {
                return err("MULFX's shift must be 0-31");
            }
            return Ok(vec![pb(0xFD, 0x10), (d << 12 | s << 8 | (n & 31)) as u16]);
        }
        "DBNZ" => {
            if k != "RE" {
                return err("DBNZ needs 'r, label'");
            }
            let r = reg_operand(&ops[0], "register")?;
            let (target, known) = ctx.target(ex(&ops[1])?)?;
            let back = ctx.pc + 2 - target;
            if known && (back & 1 != 0 || !(2..=32).contains(&back)) {
                return err("DBNZ branches back 1-16 parcels from the next instruction");
            }
            let n = if known { back / 2 - 1 } else { 0 };
            return one(p(0xF6, r, n));
        }
        "CLR" if ops.len() != 1 => return err("CLR needs a register or a memory operand"),
        "CLR" | "INC" | "DEC" if ops.len() == 1 => {
            let cell = match u {
                "CLR" => 0x20,
                "INC" => 0x21,
                _ => 0x2D,
            };
            return match &ops[0] {
                Operand::Reg(_) => {
                    let r = reg_operand(&ops[0], "register")?;
                    if u == "CLR" {
                        one(p(cell, 0, r))
                    } else {
                        // row D's in-place form
                        one(p(if u == "INC" { 0xD2 } else { 0xD3 }, r, r))
                    }
                }
                Operand::Mem(_) => {
                    let (m, r, ext) = ea(ctx, &ops[0], 1, false)?;
                    Ok(with_ext(p(cell, m, r), ext))
                }
                _ => err(format!("{u} needs a register or a memory operand")),
            };
        }
        "JMP" | "CALL" => {
            let call = u == "CALL";
            return match ops {
                [Operand::Expr(e)] => jcc(ctx, if call { 15 } else { 14 }, e),
                [op @ (Operand::Reg(_) | Operand::Imm(_) | Operand::Mem(_))] => {
                    if let Operand::Mem(mem) = op
                        && bytes(mem.size) != 4
                    {
                        return err(format!("{u} through memory needs a word"));
                    }
                    let (m, r, ext) = ea(ctx, op, 1, true)?;
                    Ok(with_ext(p(if call { 0xF1 } else { 0xF0 }, m, r), ext))
                }
                _ => err(format!(
                    "{u} needs a label, a register, #address or [memory]"
                )),
            };
        }
        "LEA" => {
            if ops.len() != 2 || !matches!(ops[0], Operand::Reg(_)) {
                return err("LEA needs 'rd, [address]'");
            }
            let rd = reg_operand(&ops[0], "register")?;
            let mut mem = match &ops[1] {
                Operand::Mem(m) => m.clone(),
                Operand::Expr(e) => Mem::new(None, Some(e.clone())),
                _ => return err("LEA needs 'rd, [address]'"),
            };
            // the size makes no difference to an address
            mem.size = None;
            let min_ext = (ctx.min_words() - 1).max(0);
            let (m, r, ext) = mem_mode(ctx, &mem, min_ext, 1, false)?;
            let cell = match m {
                // LEA rd, [R] is a copy
                2 => 0x10,
                3 => 0x04,
                4 => 0x05,
                5 => 0x06,
                0xF => 0x07,
                _ => return err("LEA needs a memory operand without auto-increment"),
            };
            return Ok(with_ext(p(cell, rd, r), ext));
        }
        _ => {}
    }

    // ---- row D, SETcc and the shifts
    if let Some(f) = index(&UNARY, u) {
        return match k {
            "RR" | "R" => {
                let d = reg_operand(&ops[0], "register")?;
                let s = if k == "RR" {
                    reg_operand(&ops[1], "register")?
                } else {
                    d
                };
                one(p(0xD0 + f, d, s))
            }
            _ => err(format!("{u} needs 'rd, rs' or 'rd'")),
        };
    }
    if let Some(cc) = u.strip_prefix("SET").and_then(cond_code) {
        if k != "R" || cc > 14 {
            return err(format!("{u} needs one register"));
        }
        return one(p(0xDF, rn(&ops[0]), cc));
    }
    if let Some(f) = index(&SHIFTS, u) {
        let base = 0xC0 + 4 * f;
        return match k {
            "RR" => one(p(base + 2, rn(&ops[0]), rn(&ops[1]))),
            "RI" => {
                let (v, known) = ctx.value(ex(&ops[1])?)?;
                if known && !(0..=31).contains(&v) {
                    return err("shift count must be 0-31");
                }
                one(p(base | (v & 1), rn(&ops[0]), (v >> 1) & 15))
            }
            _ => err(format!("{u} needs 'rd, #n' or 'rd, rs'")),
        };
    }

    // ---- branches
    let bcc = if u == "BSR" {
        Some(15)
    } else if u.len() == 3 {
        u.strip_prefix('B').and_then(cond_code)
    } else {
        None
    };
    if let Some(cc) = bcc {
        if k != "E" {
            return err(format!("{u} needs a target address"));
        }
        let e = ex(&ops[0])?;
        let (target, known) = ctx.target(e)?;
        let off = target - (ctx.pc + 2);
        if known && off & 1 != 0 {
            return err(format!("{u} target is at an odd address"));
        }
        if ctx.min_words() > 1 || (known && !(-256..=254).contains(&off)) {
            return jcc(ctx, cc, e);
        }
        return one(pb(0xB0 + cc, (off >> 1) & 0xFF));
    }
    if let Some(cc) = u.strip_prefix('J').and_then(cond_code) {
        if k != "E" {
            return err(format!("{u} needs a target address"));
        }
        return jcc(ctx, cc, ex(&ops[0])?);
    }

    // ---- moves, stores and the ALU rows
    if u == "MOV"
        && let [Operand::Mem(_), src] = ops
    {
        return match src {
            Operand::Reg(_) => {
                let rs = reg_operand(src, "register")?;
                let (m, r, ext) = ea(ctx, &ops[0], 1, false)?;
                Ok(with_ext(p(0x20 | m, rs, r), ext))
            }
            Operand::Imm(e) => {
                let (v, known) = ctx.value(e)?;
                if known && v != 0 {
                    return err("there is no store of a constant: only MOV [address], #0 (CLR)");
                }
                let (m, r, ext) = ea(ctx, &ops[0], 1, false)?;
                Ok(with_ext(p(0x20, m, r), ext))
            }
            _ => err("a store needs 'MOV [address], rs'"),
        };
    }
    if let Some(row) = ea_row(u) {
        if ops.len() != 2 || !matches!(ops[0], Operand::Reg(_)) {
            return err(format!("{u} needs 'rd, operand'"));
        }
        let rd = reg_operand(&ops[0], "register")?;
        if let Operand::Expr(_) = &ops[1] {
            return err(format!(
                "{u}: write #value for a constant or [address] for memory"
            ));
        }
        if (row == 1 || row == 6)
            && let Some(v) = u7(ctx, &ops[1])?
        {
            let cell = if row == 1 { 0x70 } else { 0x78 };
            return one(p(cell | (v & 7), rd, v >> 3));
        }
        let (m, r, ext) = ea(ctx, &ops[1], 1, row != 3)?;
        return Ok(with_ext(p(row << 4 | m, rd, r), ext));
    }
    if let Some(cell) = rr_op(u) {
        if k == "RR" {
            let (d, s) = two_regs(u, ops)?;
            return one(p(cell, d, s));
        }
        if let Some(cell) = spec_op(u)
            && ops.len() == 2
            && matches!(ops[0], Operand::Reg(_))
            && matches!(ops[1], Operand::Imm(_) | Operand::Mem(_))
        {
            let rd = reg_operand(&ops[0], "register")?;
            // only the special mode: [R + d] is its table with R as the index
            let src = match &ops[1] {
                Operand::Mem(mem)
                    if mem.base.as_ref().is_some_and(|b| b.n < 16)
                        && mem.index.is_none()
                        && !mem.postinc
                        && !mem.predec =>
                {
                    let mut t = mem.clone();
                    t.index = t.base.take();
                    t.scale = 1;
                    Operand::Mem(t)
                }
                op => op.clone(),
            };
            let (m, r, ext) = ea(ctx, &src, 1, false)?;
            if m != 0xF {
                return err(format!(
                    "{u} takes a register, or a constant, an absolute or PC-relative address or a table"
                ));
            }
            return Ok(with_ext(p(cell, rd, r), ext));
        }
        return err(if spec_op(u).is_some() {
            format!("{u} needs 'rd, rs' or 'rd, #value'")
        } else {
            format!("{u} only works on two registers")
        });
    }
    if let Some(hint) = renamed(u) {
        return err(format!("draft 2 has no {u}: {hint}"));
    }
    err(format!("unknown instruction {name}"))
}
