//! The I/O processor of RFC 0027 at microinstruction level: its core
//! ([`iop`]), the microinstruction ([`micro`]), the I/O bus and the
//! devices on its card ([`iobus`], [`flash`]), and a system on RFC 0037's
//! bus with a draft 2 CPU card that the IOP boots ([`system`]).
//!
//! The microcode and the Forth it interprets are built in Python
//! (studies/iop): this crate only runs them.

pub mod flash;
pub mod iobus;
pub mod iop;
pub mod micro;
pub mod system;

pub use iop::{Config, Iop, Status, SystemBus};
pub use system::System;
