//! The ISA-independent toolchain: the object format ([`obj`]) and the
//! linker ([`link`]). Python uses them through heron.native.toolchain, as
//! infra/obj.py and infra/link.py.

pub mod link;
pub mod obj;
