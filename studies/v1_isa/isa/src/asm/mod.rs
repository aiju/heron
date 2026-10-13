//! The draft 1a and 1b encoders for the assembler (infra/toolchain): what
//! studies/v1_isa/v1common.py, v1a.py and v1b.py did for the Python
//! assembler. This module holds what both drafts share: the system, unary
//! and shift groups and the branches, which differ only in their major
//! opcodes.

pub mod v1a;
pub mod v1b;

use toolchain::asm::expr::Expr;
use toolchain::asm::{AsmError, Ctx, Encoder, ExprRef, Operand};
use toolchain::obj::{ABS32, PC16H};

pub use v1a::V1A;
pub use v1b::V1B;

/// The encoder for an ISA named in an object file or on a command line.
pub fn encoder(name: &str) -> Option<&'static dyn Encoder> {
    match name {
        "v1a" => Some(&V1A),
        "v1b" => Some(&V1B),
        _ => None,
    }
}

const M32: i64 = 0xFFFF_FFFF;
/// The assembler refuses to place anything from here on.
const MEM_TOP: i64 = 0x10_0000;

const COND: [&str; 15] = [
    "EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE", "RA",
];
const ALU_FN: [&str; 16] = [
    "ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "BIC", "MOV", "CMP", "TST", "MULU", "MULS",
    "DIVU", "DIVS", "DIVUL",
];
const UN_FN: [&str; 12] = [
    "NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP", "SXB", "ZXB", "SXH", "ZXH", "CLZ",
];
const SHIFT_FN: [&str; 4] = ["LSL", "LSR", "ASR", "ROR"];
const SYS_FN: [&str; 14] = [
    "HALT", "NOP", "JMP", "CALL", "RET", "SAVE", "RESTORE", "RTI", "EI", "DI", "MFSR", "MTSR",
    "SWI", "SET",
];

fn err<T>(msg: impl Into<String>) -> Result<T, AsmError> {
    Err(AsmError::new(msg))
}

fn index(names: &[&str], name: &str) -> Option<i64> {
    names.iter().position(|&n| n == name).map(|i| i as i64)
}

/// The registers both drafts share: r0-r15, and sp for r15.
fn register(name: &str) -> Option<u32> {
    if name == "sp" {
        return Some(15);
    }
    let n: u32 = name.strip_prefix('r')?.parse().ok()?;
    (n < 16 && format!("r{n}") == name).then_some(n)
}

/// A parcel from its four fields.
fn w(op: i64, a: i64, b: i64, c: i64) -> u16 {
    (((op & 15) << 12) | ((a & 15) << 8) | ((b & 15) << 4) | (c & 15)) as u16
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

/// The major opcodes that differ between the drafts.
struct OpMap {
    un: i64,
    sh: i64,
    bcc: i64,
    jcc: i64,
}

/// Instructions encoded the same way in both drafts; None if `u` isn't
/// one of them.
fn asm_common(
    u: &str,
    ops: &[Operand],
    ctx: &mut Ctx,
    m: &OpMap,
) -> Result<Option<Vec<u16>>, AsmError> {
    let k = toolchain::asm::kinds(ops);
    let k = k.as_str();
    let sys = |name: &str| index(&SYS_FN, name).unwrap_or(0);
    let one = |v: u16| Ok(Some(vec![v]));

    // ---- system group ----
    match u {
        "HALT" | "NOP" | "RET" | "RTI" | "EI" | "DI" => {
            if !ops.is_empty() {
                return err(format!("{u} takes no operands"));
            }
            return one(w(0, 0, 0, sys(u)));
        }
        "SAVE" | "RESTORE" => {
            let (a, b) = reg_range(ops)?;
            return one(w(0, a, b, sys(u)));
        }
        "MFSR" => {
            if ops.len() != 2 {
                return err("MFSR needs 'rd, n'");
            }
            let rd = reg_operand(&ops[0], "register")?;
            let n = sr_number(ctx, &ops[1])?;
            return one(w(0, rd, n, 10));
        }
        "MTSR" => {
            if ops.len() != 2 {
                return err("MTSR needs 'n, rs'");
            }
            let n = sr_number(ctx, &ops[0])?;
            let rs = reg_operand(&ops[1], "register")?;
            return one(w(0, n, rs, 11));
        }
        "MFF" | "MFHI" | "MTF" | "MTHI" => {
            if k != "R" {
                return err(format!("{u} needs one register"));
            }
            let sr = i64::from(u.ends_with("HI"));
            return one(if u.starts_with("MF") {
                w(0, rn(&ops[0]), sr, 10)
            } else {
                w(0, sr, rn(&ops[0]), 11)
            });
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
            return one(w(0, v >> 4, v, 12));
        }
        _ => {}
    }
    if let Some(cc) = u.strip_prefix("SET").and_then(cond_code) {
        if k != "R" {
            return err(format!("{u} needs one register"));
        }
        return one(w(0, rn(&ops[0]), cc, 13));
    }

    // ---- unary group ----
    if let Some(f) = index(&UN_FN, u) {
        return match k {
            "RR" => one(w(m.un, rn(&ops[0]), rn(&ops[1]), f)),
            "R" => one(w(m.un, rn(&ops[0]), rn(&ops[0]), f)),
            _ => err(format!("{u} needs 'rd, rs' or 'rd'")),
        };
    }

    // ---- shift group ----
    if let Some(f) = index(&SHIFT_FN, u) {
        return match k {
            "RR" => one(w(m.sh, rn(&ops[0]), rn(&ops[1]), 8 | f)),
            "RI" => {
                let (v, known) = ctx.value(ex(&ops[1])?)?;
                if known && !(0..=31).contains(&v) {
                    return err("shift count must be 0-31");
                }
                one(w(m.sh, rn(&ops[0]), v & 15, (((v >> 4) & 1) << 2) | f))
            }
            _ => err(format!("{u} needs 'rd, #n' or 'rd, rs'")),
        };
    }

    // ---- branches ----
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
            return jcc(ctx, m.jcc, cc, e).map(Some);
        }
        return one(w(m.bcc, cc, 0, 0) | ((off >> 1) & 0xFF) as u16);
    }
    if (u == "JMP" || u == "CALL") && k == "E" {
        return jcc(ctx, m.jcc, if u == "JMP" { 14 } else { 15 }, ex(&ops[0])?).map(Some);
    }
    if (u == "JMP" || u == "CALL") && k == "R" {
        return one(w(0, 0, rn(&ops[0]), sys(u)));
    }
    if let Some(cc) = u.strip_prefix('J').and_then(cond_code) {
        if k != "E" {
            return err(format!("{u} needs a target address"));
        }
        return jcc(ctx, m.jcc, cc, ex(&ops[0])?).map(Some);
    }
    Ok(None)
}

fn jcc(ctx: &mut Ctx, op: i64, cc: i64, e: &ExprRef) -> Result<Vec<u16>, AsmError> {
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
        return Ok(vec![w(op, cc, 1, 0), (t & 0xFFFF) as u16, (t >> 16) as u16]);
    }
    ctx.fix(1, PC16H, Some(e), next)?;
    Ok(vec![w(op, cc, 0, 0), ((off >> 1) & 0xFFFF) as u16])
}

/// `r8-r11`, or a single register.
fn reg_range(ops: &[Operand]) -> Result<(i64, i64), AsmError> {
    let (a, b) = match ops {
        [Operand::Reg(r)] => (r.n as i64, r.n as i64),
        [Operand::RegRange(a, b)] => (a.n as i64, b.n as i64),
        _ => return err("expected a register range like r8-r11"),
    };
    if !(1 <= a && a <= b && b <= 14) {
        return err("register range must be within r1-r14, low to high");
    }
    Ok((a, b))
}

fn sr_number(ctx: &mut Ctx, op: &Operand) -> Result<i64, AsmError> {
    if let Operand::Expr(e) = op
        && let Expr::Sym(name) = &**e
    {
        match name.to_ascii_lowercase().as_str() {
            "flags" => return Ok(0),
            "hi" => return Ok(1),
            _ => {}
        }
    }
    let Some(e) = op.expr() else {
        return err("expected a special register number");
    };
    let (v, _) = ctx.value(e)?;
    if v != 0 && v != 1 {
        return err("special register must be 0 (flags) or 1 (hi)");
    }
    Ok(v)
}
