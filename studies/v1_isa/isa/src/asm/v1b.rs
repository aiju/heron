//! The draft 1b encoder: register + addressing mode, 16-bit parcels
//! (RFC 0004, Part II). Main format `F D M R`: operation, register, mode,
//! register-or-constant for the mode.

use toolchain::asm::{AsmError, Ctx, Encoder, ExprRef, Mem, Operand, Reg, Size, kinds};
use toolchain::obj::{ABS16S, ABS32, PC16};

use super::{MEM_TOP, OpMap, as_signed, asm_common, err, ex, index, norm32, reg_operand, rn, w};

const OP_JCC: i64 = 0xA;
const OP_JEA: i64 = 0xB;
const OP_UN: i64 = 0xC;
const OP_SH: i64 = 0xD;
const OP_BCC: i64 = 0xE;
const OP_RR: i64 = 0xF;

const OPMAP: OpMap = OpMap {
    un: OP_UN,
    sh: OP_SH,
    bcc: OP_BCC,
    jcc: OP_JCC,
};

/// The instructions with an effective address, and their opcodes.
fn ea_op(u: &str) -> Option<i64> {
    Some(match u {
        "MOV" => 0x1,
        "ST" => 0x2,
        "LEA" => 0x3,
        "ADD" => 0x4,
        "SUB" => 0x5,
        "CMP" => 0x6,
        "AND" => 0x7,
        "OR" => 0x8,
        "XOR" => 0x9,
        _ => return None,
    })
}

const RR_FN: [&str; 9] = [
    "ADC", "SBC", "BIC", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL",
];

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

pub struct V1b;

pub static V1B: V1b = V1b;

impl Encoder for V1b {
    fn name(&self) -> &'static str {
        "v1b"
    }

    fn register(&self, name: &str) -> Option<u32> {
        // pc only means something as [pc + label]
        if name == "pc" {
            Some(16)
        } else {
            super::register(name)
        }
    }

    fn word_bytes(&self) -> i64 {
        4
    }

    fn mem_top(&self) -> i64 {
        MEM_TOP
    }

    fn assemble(&self, name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
        assemble(name, ops, ctx, None)
    }
}

/// A mode: (M, R, extension parcels).
type Mode = (i64, i64, Vec<u16>);

/// A constant operand.
fn imm_mode(ctx: &mut Ctx, e: &ExprRef, min_ext: i64, n_before: i64) -> Result<Mode, AsmError> {
    let (mut v, known) = ctx.value(e)?;
    if known {
        v = norm32(v)?;
    }
    let sv = as_signed(v);
    if min_ext == 0 {
        if (0..=15).contains(&sv) {
            return Ok((1, sv, vec![]));
        }
        if (-16..=-1).contains(&sv) {
            return Ok((0xD, -sv - 1, vec![]));
        }
    }
    if min_ext <= 1 {
        if (-32768..=32767).contains(&sv) {
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

/// A memory operand. `rt`: the fixed-base register of mode E, if the
/// machine has one (Isa::parse).
fn mem_mode(
    ctx: &mut Ctx,
    mem: &Mem,
    min_ext: i64,
    n_before: i64,
    rt: Option<i64>,
) -> Result<Mode, AsmError> {
    let size = bytes(mem.size);
    let next = ctx.pc + 2 * (n_before + 1);
    if let Some(base) = &mem.base
        && base.n == 16
    {
        // [pc + label]
        if mem.index.is_some() || mem.postinc || mem.predec {
            return err("[pc + ...] takes only a label");
        }
        let (target, known) = match &mem.disp {
            Some(d) => ctx.target(d)?,
            None => (0, true),
        };
        let off = target - next;
        if known && !(-32768..=32767).contains(&off) {
            return err("PC-relative target out of range (±32 KB)");
        }
        if mem.disp.is_some() {
            ctx.fix(n_before, PC16, mem.disp.as_ref(), next)?;
        }
        return Ok((
            0xF,
            by_size(size, 0xA, 0xB, 0xC),
            vec![(off & 0xFFFF) as u16],
        ));
    }
    let base_n = mem.base.as_ref().map_or(0, |r| r.n as i64);
    if mem.postinc || mem.predec {
        if mem.postinc {
            return match size {
                4 => Ok((6, base_n, vec![])),
                1 => Ok((0xA, base_n, vec![])),
                _ => err("there is no half [r]+ mode"),
            };
        }
        if size != 4 {
            return err("-[r] only exists for words");
        }
        return Ok((7, base_n, vec![]));
    }
    if let Some(index) = &mem.index {
        let scale = match mem.scale {
            1 => 0,
            2 => 1,
            4 => 2,
            8 => 3,
            _ => return err("index scale must be 1, 2, 4 or 8"),
        };
        if index.n > 15 {
            return err("bad index register");
        }
        let (d8, known) = match &mem.disp {
            Some(d) => ctx.value(d)?,
            None => (0, true),
        };
        if known && !(-128..=127).contains(&as_signed(norm32(d8)?)) {
            return err("the indexed mode's displacement must fit in 8 bits");
        }
        let z = by_size(size, 2, 0, 1);
        let e = ((index.n as i64) << 12) | (scale << 10) | (z << 8) | (d8 & 0xFF);
        return Ok((5, base_n, vec![e as u16]));
    }
    let (mut disp, known) = match &mem.disp {
        Some(d) => ctx.value(d)?,
        None => (0, true),
    };
    if known {
        disp = norm32(disp)?;
    }
    let sd = as_signed(disp);
    if mem.base.is_none() {
        // absolute
        if min_ext <= 1 && (!known || (-32768..=32767).contains(&sd)) {
            if mem.disp.is_some() {
                ctx.fix(n_before, ABS16S, mem.disp.as_ref(), 0)?;
            }
            return Ok((0xF, by_size(size, 4, 5, 6), vec![(disp & 0xFFFF) as u16]));
        }
        let off = disp - next;
        if min_ext <= 1 && known && ctx.abs_pc() && (-32768..=32767).contains(&off) {
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
    }
    let b = base_n;
    if known && !(-32768..=32767).contains(&sd) {
        return err("displacement doesn't fit in 16 bits: compute the address in a register");
    }
    if min_ext == 0 && known && sd == 0 {
        return Ok((by_size(size, 2, 8, 0xB), b, vec![]));
    }
    if min_ext == 0 && known && b == 15 && size == 4 && (0..=60).contains(&sd) && sd % 4 == 0 {
        return Ok((4, sd / 4, vec![]));
    }
    if min_ext == 0 && known && Some(b) == rt && size == 4 && (0..=60).contains(&sd) && sd % 4 == 0
    {
        return Ok((0xE, sd / 4, vec![]));
    }
    if mem.disp.is_some() {
        ctx.fix(n_before, ABS16S, mem.disp.as_ref(), 0)?;
    }
    Ok((by_size(size, 3, 9, 0xC), b, vec![(disp & 0xFFFF) as u16]))
}

/// An operand's mode.
fn ea(ctx: &mut Ctx, op: &Operand, n_before: i64, rt: Option<i64>) -> Result<Mode, AsmError> {
    let min_ext = (ctx.min_words() - n_before).max(0);
    match op {
        Operand::Reg(r) => {
            if r.n > 15 {
                return err("pc can only be used as [pc + label]");
            }
            Ok((0, r.n as i64, vec![]))
        }
        Operand::Imm(e) => imm_mode(ctx, e, min_ext, n_before),
        Operand::Mem(m) => mem_mode(ctx, m, min_ext, n_before, rt),
        _ => err("expected a register, #constant or [memory] operand"),
    }
}

fn sp_mem(postinc: bool) -> Operand {
    let mut m = Mem::new(
        Some(Reg {
            n: 15,
            name: "sp".to_string(),
        }),
        None,
    );
    m.postinc = postinc;
    m.predec = !postinc;
    Operand::Mem(m)
}

fn with_ext(first: u16, ext: Vec<u16>) -> Vec<u16> {
    let mut out = vec![first];
    out.extend(ext);
    out
}

/// Assemble one instruction; `rt` as for mem_mode.
pub(super) fn assemble(
    name: &str,
    ops: &[Operand],
    ctx: &mut Ctx,
    rt: Option<i64>,
) -> Result<Vec<u16>, AsmError> {
    let u = name.to_ascii_uppercase();
    let u = u.as_str();
    let k = kinds(ops);
    let k = k.as_str();

    if u == "PUSH" || u == "POP" {
        if k != "R" {
            return err(format!("{u} needs one register"));
        }
        let (op, postinc) = if u == "PUSH" {
            ("ST", false)
        } else {
            ("MOV", true)
        };
        return assemble(op, &[ops[0].clone(), sp_mem(postinc)], ctx, rt);
    }
    if u == "LI" {
        if k != "RE" && k != "RI" {
            return err("LI needs 'rd, value'");
        }
        return assemble(
            "MOV",
            &[ops[0].clone(), Operand::Imm(ex(&ops[1])?.clone())],
            ctx,
            rt,
        );
    }
    if (u == "JMP" || u == "CALL") && (k == "M" || k == "I") {
        let (m, r, ext) = ea(ctx, &ops[0], 1, rt)?;
        if let Operand::Mem(mem) = &ops[0]
            && bytes(mem.size) != 4
        {
            return err(format!("{u} through memory needs a word"));
        }
        return Ok(with_ext(w(OP_JEA, i64::from(u == "CALL"), m, r), ext));
    }

    if let Some(out) = asm_common(u, ops, ctx, &OPMAP)? {
        return Ok(out);
    }

    if let Some(op) = ea_op(u) {
        if ops.len() != 2 || !matches!(ops[0], Operand::Reg(_)) {
            return err(format!("{u} needs 'rd, operand'"));
        }
        let rd = reg_operand(&ops[0], "register")?;
        let lea;
        let src = match &ops[1] {
            Operand::Expr(e) if u == "LEA" => {
                lea = Operand::Mem(Mem::new(None, Some(e.clone())));
                &lea
            }
            Operand::Expr(_) => {
                return err(format!(
                    "{u}: write #value for a constant or [address] for memory"
                ));
            }
            src => src,
        };
        let (m, r, ext) = ea(ctx, src, 1, rt)?;
        if u == "ST" && (matches!(m, 0 | 1 | 0xD) || (m == 0xF && r <= 3)) {
            return err("ST needs a memory operand");
        }
        if u == "LEA" && (matches!(m, 0 | 1 | 0xD | 6 | 7 | 0xA) || (m == 0xF && r <= 3)) {
            return err("LEA needs a memory operand without auto-increment");
        }
        return Ok(with_ext(w(op, rd, m, r), ext));
    }

    if let Some(f) = index(&RR_FN, u) {
        if k != "RR" {
            return err(format!("{u} only works on two registers in draft 1b"));
        }
        return Ok(vec![w(OP_RR, rn(&ops[0]), rn(&ops[1]), f)]);
    }
    if matches!(u, "MVI" | "ADDI" | "CMPI") {
        return err(format!("draft 1b has no {u}: use MOV/ADD/CMP with #value"));
    }
    err(format!("unknown instruction {name}"))
}
