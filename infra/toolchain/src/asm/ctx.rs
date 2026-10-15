//! What an encoder sees of the assembly: the statement's address, its
//! operands' values, and the fields the linker fills in.

use std::collections::HashSet;
use std::sync::Arc;

use super::expr::{self, EvalError, Expr};
use super::{
    AsmError, Base, ExprRef, Fixup, REP_FAR, REP_NEAR, REP_PC, Stmt, Tables, Where, undefined,
};
use crate::obj;

fn id(e: &ExprRef) -> usize {
    Arc::as_ptr(e) as usize
}

/// What encoding one statement left behind.
#[derive(Default)]
pub(super) struct Out {
    /// operands that need a relocation (object files)
    pub pending: Vec<ExprRef>,
    /// the operands fixed, by identity
    fixed: HashSet<usize>,
    pub relocs: Vec<Fixup>,
    pub warnings: Vec<String>,
}

impl Out {
    pub fn check_fixed(&self) -> Result<(), AsmError> {
        for e in &self.pending {
            if !self.fixed.contains(&id(e)) {
                let names: Vec<String> = expr::symbols_in(e).into_iter().collect();
                let names = if names.is_empty() {
                    "this".to_string()
                } else {
                    names.join(", ")
                };
                return Err(AsmError::new(format!(
                    "the linker fills in the address of {names}, but this operand can't hold it"
                )));
            }
        }
        Ok(())
    }
}

/// The assembly context passed to the encoder.
pub struct Ctx<'a> {
    t: &'a Tables,
    /// The statement's address (or offset in its section).
    pub pc: i64,
    section: Option<&'a Arc<str>>,
    sticky_long: bool,
    size: i64,
    at: &'a Where,
    pub(super) out: Out,
}

impl<'a> Ctx<'a> {
    pub(super) fn new(t: &'a Tables, st: &'a Stmt) -> Ctx<'a> {
        Ctx {
            t,
            pc: st.addr,
            section: st.section.as_ref(),
            sticky_long: st.sticky_long,
            size: st.size,
            at: &st.at,
            out: Out::default(),
        }
    }

    /// True if `pc` is the final address (not an offset in a section the
    /// linker will place).
    pub fn abs_pc(&self) -> bool {
        self.section.is_none()
    }

    pub fn final_pass(&self) -> bool {
        self.t.final_pass
    }

    /// True once this statement has been forced to its long form.
    pub fn long(&self) -> bool {
        self.sticky_long
    }

    /// Once a statement has grown, its encoding may never get shorter again
    /// (so the passes converge): ISAs with several sizes pick a form of at
    /// least this many words.
    pub fn min_words(&self) -> i64 {
        if self.sticky_long { self.size / 2 } else { 0 }
    }

    fn rel(&self, e: &Expr) -> Result<Option<(i64, Option<Base>)>, AsmError> {
        match self.t.eval_rel(e, self.pc, self.section) {
            Ok(r) => Ok(Some(r)),
            Err(EvalError::Unresolved(name)) if self.t.final_pass => Err(undefined(&name)),
            Err(EvalError::Unresolved(_)) => Ok(None),
            Err(EvalError::Asm(e)) => Err(e),
        }
    }

    /// Evaluate an expression used as a number (an immediate, an absolute
    /// address, a displacement): (value, known).
    pub fn value(&mut self, e: &ExprRef) -> Result<(i64, bool), AsmError> {
        if !self.t.relocatable {
            return match expr::eval(e, &|n| self.t.symbols.get(n), self.pc) {
                Ok(v) => Ok((v, true)),
                Err(EvalError::Unresolved(name)) if self.t.final_pass => Err(undefined(&name)),
                Err(EvalError::Unresolved(_)) => Ok((0, false)),
                Err(EvalError::Asm(e)) => Err(e),
            };
        }
        let Some((v, base)) = self.rel(e)? else {
            return Ok((0, false));
        };
        let Some(base) = base else {
            return Ok((v, true));
        };
        self.out.pending.push(e.clone());
        let rep = if self.t.is_far(&base) {
            REP_FAR
        } else {
            REP_NEAR
        };
        Ok((rep.wrapping_add(v), true))
    }

    /// Evaluate a branch target or other PC-relative operand: the address,
    /// comparable with `pc`: (value, known).
    pub fn target(&mut self, e: &ExprRef) -> Result<(i64, bool), AsmError> {
        if !self.t.relocatable {
            return self.value(e);
        }
        let Some((v, base)) = self.rel(e)? else {
            return Ok((0, false));
        };
        if let Some(d) = self.t.direct(base.as_ref(), self.section) {
            return Ok((v.wrapping_add(d), true));
        }
        self.out.pending.push(e.clone());
        Ok((self.pc.wrapping_add(REP_PC), true))
    }

    /// Parcel `index` of the encoding holds `e` (`kind`: a relocation kind
    /// from [`crate::obj`]; for the PC-relative kinds, `base` is the
    /// address the CPU adds the field to). Records a relocation when the
    /// linker has to fill the field in; does nothing for assembly-time
    /// constants.
    pub fn fix(
        &mut self,
        index: i64,
        kind: u32,
        e: Option<&ExprRef>,
        base: i64,
    ) -> Result<(), AsmError> {
        let Some(e) = e else {
            return Ok(());
        };
        self.out.fixed.insert(id(e));
        if !self.t.relocatable || !self.t.final_pass {
            return Ok(());
        }
        let Some((mut v, b)) = self.rel(e)? else {
            return Ok(());
        };
        let field = self.pc + 2 * index;
        if obj::pc_relative(kind) {
            if self.t.direct(b.as_ref(), self.section).is_some() {
                return Ok(());
            }
            v -= base - field;
        } else if b.is_none() {
            return Ok(());
        }
        self.out.relocs.push(Fixup {
            offset: field,
            kind,
            base: b,
            addend: v,
        });
        Ok(())
    }

    pub fn warn(&mut self, msg: &str) {
        if self.t.final_pass {
            let (file, line) = self.at;
            self.out.warnings.push(format!("{file}:{line}: {msg}"));
        }
    }
}
