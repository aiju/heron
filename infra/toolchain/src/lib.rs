//! The ISA-independent toolchain: the assembler core ([`asm`]), the object
//! format ([`obj`]) and the linker ([`link`]). An ISA supplies the
//! assembler its [`asm::Encoder`] (drafts 1a and 1b: studies/v1_isa/isa).
//! Python uses them through heron.native.toolchain, as infra/asm.py,
//! infra/obj.py and infra/link.py.

pub mod asm;
pub mod link;
pub mod obj;
