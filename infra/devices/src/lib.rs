//! Register-level models of the I/O devices: what software sees in their
//! registers, and when, without their pins. The chip-level simulator
//! (infra/hwsim) wraps them in pin-level models, and the instruction-level
//! system model calls them directly.
//!
//! Each model keeps time in its own unit and only moves when it's told
//! to: the UART in XIN clock cycles ([`uart16550`]), the timer in CLK
//! pulses ([`i8254`]), the CompactFlash card and the clock chip in
//! nanoseconds ([`cf`], [`ds1302`]). Each can say when it will next change
//! on its own, so a caller can skip the time in between.

pub mod cf;
pub mod ds1302;
pub mod i8254;
pub mod uart16550;
