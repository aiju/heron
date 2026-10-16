//! Register-level models of the I/O devices: what software sees in their
//! registers, and when, without their pins. The chip-level simulator
//! (infra/hwsim) wraps them in pin-level models, and the instruction-level
//! system model calls them directly.
//!
//! Each model keeps time in its own unit and only moves when it's told
//! to: the UART in XIN clock cycles ([`uart16550`]), the timer in CLK
//! pulses ([`i8254`]), the CompactFlash card in nanoseconds ([`cf`]). Each
//! can say when it will next change on its own, so a caller can skip the
//! time in between.

pub mod cf;
pub mod i8254;
pub mod uart16550;

/// A device a frontend gives a machine, for the accesses the machine has
/// nothing of its own for: on the draft 1 and draft 2 machines without a
/// supervisor, the I/O page's registers from 0x20 on and the addresses
/// outside RAM and the I/O page (a frame buffer and its input, say). Time
/// is the machine's cycle count.
pub trait Device: std::any::Any + Send + Sync {
    /// A read of `size` bytes (1, 2 or 4, aligned) at `a`, or None if
    /// nothing answers there.
    fn read(&mut self, a: u32, size: u32, cycles: u64) -> Option<u32>;
    /// A write; false if nothing answers.
    fn write(&mut self, a: u32, size: u32, value: u32, cycles: u64) -> bool;
}
