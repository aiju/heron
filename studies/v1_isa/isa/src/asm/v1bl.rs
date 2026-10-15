//! The v1bl encoder: draft 1b with a link register (studies/link_register).
//! The encoding is draft 1b's; only what `BSR`, `CALL` and `RET` do
//! differs, so this is the 1b encoder under its own name, which keeps 1b
//! and v1bl object files from being linked together.

use toolchain::asm::{AsmError, Ctx, Encoder, Operand};

use super::v1b::V1B;

pub struct V1bl;

pub static V1BL: V1bl = V1bl;

impl Encoder for V1bl {
    fn name(&self) -> &'static str {
        "v1bl"
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
        V1B.assemble(name, ops, ctx)
    }
}
