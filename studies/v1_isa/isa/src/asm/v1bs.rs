//! The v1bs encoder: draft 1b plus the system extensions of the kernel
//! study (sys.rs). It adds `MFUR rd, rs` and `MTUR rd, rs` (system
//! functions E and F) and the system special registers by name for
//! `MFSR`/`MTSR`; everything else is draft 1b's.

use toolchain::asm::expr::Expr;
use toolchain::asm::{AsmError, Ctx, Encoder, Operand};

use super::v1b::V1B;
use super::{err, reg_operand, w};
use crate::sys::SR_NAMES;

pub struct V1bs;

pub static V1BS: V1bs = V1bs;

/// A special register: a name (sys::SR_NAMES) or a number 0-15.
fn sr(ctx: &mut Ctx, op: &Operand) -> Result<i64, AsmError> {
    if let Operand::Expr(e) = op
        && let Expr::Sym(name) = &**e
        && let Some(i) = SR_NAMES.iter().position(|n| name.eq_ignore_ascii_case(n))
    {
        return Ok(i as i64);
    }
    let Some(e) = op.expr() else {
        return err("expected a special register");
    };
    let (v, _) = ctx.value(e)?;
    if !(0..=15).contains(&v) {
        return err("special register must be 0-15");
    }
    Ok(v)
}

impl Encoder for V1bs {
    fn name(&self) -> &'static str {
        "v1bs"
    }

    fn register(&self, name: &str) -> Option<u32> {
        V1B.register(name)
    }

    fn word_bytes(&self) -> i64 {
        V1B.word_bytes()
    }

    fn mem_top(&self) -> i64 {
        V1B.mem_top()
    }

    fn assemble(&self, name: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
        let u = name.to_ascii_uppercase();
        match u.as_str() {
            "MFSR" | "MTSR" => {
                if ops.len() != 2 {
                    return err(format!("{u} needs a register and a special register"));
                }
                Ok(vec![if u == "MFSR" {
                    w(0, reg_operand(&ops[0], "register")?, sr(ctx, &ops[1])?, 10)
                } else {
                    w(0, sr(ctx, &ops[0])?, reg_operand(&ops[1], "register")?, 11)
                }])
            }
            "MFUR" | "MTUR" => {
                if ops.len() != 2 {
                    return err(format!("{u} needs 'rd, rs'"));
                }
                let a = reg_operand(&ops[0], "register")?;
                let b = reg_operand(&ops[1], "register")?;
                Ok(vec![w(0, a, b, if u == "MFUR" { 14 } else { 15 })])
            }
            _ => V1B.assemble(name, ops, ctx),
        }
    }
}
