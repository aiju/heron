//! The draft 1a encoder: load/store, 16-bit parcels (RFC 0004, Part I).

use toolchain::asm::{AsmError, Ctx, Encoder, Operand, kinds};
use toolchain::obj::{ABS16S, ABS32, PC16};

use super::{ALU_FN, MEM_TOP, OpMap, as_signed, asm_common, err, ex, index, norm32, rn, w};

const OP_ALU: i64 = 0x1;
const OP_UN: i64 = 0x2;
const OP_BCC: i64 = 0x3;
const OP_LD: i64 = 0x4;
const OP_ST: i64 = 0x5;
const OP_LDB: i64 = 0x6;
const OP_STB: i64 = 0x7;
const OP_ALUI: i64 = 0x8;
const OP_JCC: i64 = 0x9;
const OP_MEML: i64 = 0xA;
const OP_SH: i64 = 0xB;
const OP_MVI: i64 = 0xC;
const OP_ADDI: i64 = 0xD;
const OP_CMPI: i64 = 0xE;

const OPMAP: OpMap = OpMap {
    un: OP_UN,
    sh: OP_SH,
    bcc: OP_BCC,
    jcc: OP_JCC,
};

/// The long memory functions (op A): (function with disp16, with disp32).
fn mem_fn(u: &str) -> Option<(i64, Option<i64>)> {
    Some(match u {
        "LD" => (0, Some(0xA)),
        "ST" => (1, Some(0xB)),
        "LDB" => (2, Some(0xC)),
        "STB" => (3, Some(0xD)),
        "LDH" => (4, None),
        "STH" => (5, None),
        "LDSB" => (6, None),
        "LDSH" => (7, None),
        "LEA" => (8, Some(0xE)),
        _ => return None,
    })
}

/// Op 8's immediate kind for a 32-bit pattern.
fn imm_kind(v: i64, min_words: i64) -> i64 {
    let sv = as_signed(v);
    if min_words <= 2 {
        if (-32768..=32767).contains(&sv) {
            return 0;
        }
        if v <= 0xFFFF {
            return 1;
        }
        if v & 0xFFFF == 0 {
            return 2;
        }
    }
    3
}

fn imm_parcels(k: i64, v: i64) -> Vec<u16> {
    match k {
        0 | 1 => vec![(v & 0xFFFF) as u16],
        2 => vec![(v >> 16) as u16],
        _ => vec![(v & 0xFFFF) as u16, (v >> 16) as u16],
    }
}

pub struct V1a;

pub static V1A: V1a = V1a;

impl Encoder for V1a {
    fn name(&self) -> &'static str {
        "v1a"
    }

    fn register(&self, name: &str) -> Option<u32> {
        super::register(name)
    }

    fn word_bytes(&self) -> i64 {
        4
    }

    fn mem_top(&self) -> i64 {
        MEM_TOP
    }

    fn assemble(&self, name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
        assemble(name, ops, ctx)
    }
}

fn assemble(name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
    let u = name.to_ascii_uppercase();
    let u = u.as_str();
    let k = kinds(ops);
    let k = k.as_str();

    let common = match u {
        "PUSH" => "SAVE",
        "POP" => "RESTORE",
        u => u,
    };
    if let Some(out) = asm_common(common, ops, ctx, &OPMAP)? {
        return Ok(out);
    }

    // ---- two-operand ALU ----
    if let Some(f) = index(&ALU_FN, u) {
        if k == "RR" {
            return Ok(vec![w(OP_ALU, rn(&ops[0]), rn(&ops[1]), f)]);
        }
        if k == "RI" {
            let rd = rn(&ops[0]);
            let e = ex(&ops[1])?;
            let (mut v, known) = ctx.value(e)?;
            if known {
                v = norm32(v)?;
            }
            let sv = as_signed(v);
            let short = match u {
                "MOV" => Some(OP_MVI),
                "CMP" => Some(OP_CMPI),
                _ => None,
            };
            if let Some(op) = short
                && ctx.min_words() <= 1
                && (-128..=127).contains(&sv)
            {
                return Ok(vec![w(op, rd, 0, 0) | (sv & 0xFF) as u16]);
            }
            let kind = imm_kind(v, ctx.min_words());
            if kind == 0 || kind == 3 {
                ctx.fix(1, if kind == 0 { ABS16S } else { ABS32 }, Some(e), 0)?;
            }
            let mut out = vec![w(OP_ALUI, rd, kind, f)];
            out.extend(imm_parcels(kind, v));
            return Ok(out);
        }
        return err(format!("{u} needs 'rd, rs' or 'rd, #imm'"));
    }
    if u == "LI" {
        if k != "RE" && k != "RI" {
            return err("LI needs 'rd, value'");
        }
        return assemble(
            "MOV",
            &[ops[0].clone(), Operand::Imm(ex(&ops[1])?.clone())],
            ctx,
        );
    }
    if matches!(u, "MVI" | "ADDI" | "CMPI") {
        if k != "RE" && k != "RI" {
            return err(format!("{u} needs 'rd, imm8'"));
        }
        let (mut v, known) = ctx.value(ex(&ops[1])?)?;
        if known {
            v = as_signed(norm32(v)?);
            if !(-128..=127).contains(&v) {
                return err(format!(
                    "value {v} doesn't fit in a signed 8-bit immediate (-128..127)"
                ));
            }
        }
        let op = match u {
            "MVI" => OP_MVI,
            "ADDI" => OP_ADDI,
            _ => OP_CMPI,
        };
        return Ok(vec![w(op, rn(&ops[0]), 0, 0) | (v & 0xFF) as u16]);
    }

    // ---- loads, stores, LEA ----
    if let Some((f16, f32)) = mem_fn(u) {
        if u == "LEA" && k == "RE" {
            // PC-relative: rd <- PC + disp16
            let e = ex(&ops[1])?;
            let (target, known) = ctx.target(e)?;
            let next = ctx.pc + 4;
            let off = target - next;
            if ctx.min_words() <= 2 && (!known || (-32768..=32767).contains(&off)) {
                ctx.fix(1, PC16, Some(e), next)?;
                return Ok(vec![w(OP_MEML, rn(&ops[0]), 0, 9), (off & 0xFFFF) as u16]);
            }
            let (t, known) = ctx.value(e)?;
            let t = if known { norm32(t)? } else { 0 };
            ctx.fix(1, ABS32, Some(e), 0)?;
            return Ok(vec![
                w(OP_MEML, rn(&ops[0]), 0, 0xE),
                (t & 0xFFFF) as u16,
                (t >> 16) as u16,
            ]);
        }
        let (true, Some(Operand::Mem(mem))) = (k == "RM", ops.get(1)) else {
            return err(format!("{u} needs 'reg, [base + offset]'"));
        };
        if mem.index.is_some() {
            return err(
                "draft 1a has no register + register addressing: add the registers first, \
                 or use [label + reg] for a static array",
            );
        }
        if !mem.plain() {
            return err(
                "draft 1a has no size keywords or auto-increment: the size is in the mnemonic",
            );
        }
        let rd = rn(&ops[0]);
        let base = mem.base.as_ref().map_or(0, |r| r.n as i64);
        if base > 15 {
            return err("bad base register");
        }
        let (mut disp, known) = match &mem.disp {
            None => (0, true),
            Some(d) => ctx.value(d)?,
        };
        if known {
            disp = norm32(disp)?;
        }
        let sd = as_signed(disp);
        if ctx.min_words() <= 1 && known {
            if (u == "LD" || u == "ST") && (0..=60).contains(&sd) && sd % 4 == 0 {
                return Ok(vec![w(
                    if u == "LD" { OP_LD } else { OP_ST },
                    rd,
                    base,
                    sd / 4,
                )]);
            }
            if (u == "LDB" || u == "STB") && (0..=15).contains(&sd) {
                return Ok(vec![w(
                    if u == "LDB" { OP_LDB } else { OP_STB },
                    rd,
                    base,
                    sd,
                )]);
            }
        }
        if ctx.min_words() <= 2 && (!known || (-32768..=32767).contains(&sd)) {
            if mem.disp.is_some() {
                ctx.fix(1, ABS16S, mem.disp.as_ref(), 0)?;
            }
            return Ok(vec![w(OP_MEML, rd, base, f16), (disp & 0xFFFF) as u16]);
        }
        let Some(f32) = f32 else {
            return err(format!(
                "{u} only has a 16-bit displacement: put the address in a register"
            ));
        };
        ctx.fix(1, ABS32, mem.disp.as_ref(), 0)?;
        return Ok(vec![
            w(OP_MEML, rd, base, f32),
            (disp & 0xFFFF) as u16,
            (disp >> 16) as u16,
        ]);
    }

    err(format!("unknown instruction {name}"))
}
