//! The system half of draft 2 (reports/0029-rfc-draft-2-system.md, Part
//! I): supervisor and user mode, the status register, the address space
//! with the supervisor's window and the page map, special registers 8-15,
//! register banks, precise vectored exceptions and interrupts at eight
//! levels.
//!
//! A machine made with [`crate::Machine::new_system`] has it; one made with
//! [`crate::Machine::new`] is the machine around the instructions that the
//! programs run on, draft 1's (studies/v2_isa/README.md), and never comes
//! here. Physical addresses beyond RAM go to a [`Bus`], which the board
//! supplies: its devices, and the interrupt lines.
//!
//! Where RFC 0029 leaves a choice open, this takes the proposal it states,
//! or makes one, marked in the comments:
//! - `MTSR sr` changes every bit but S (RFC 0029, 2);
//! - an access to a physical address that nothing answers is a bus error,
//!   through the reserved vector `0x8000_000C`, with `far` set (open);
//! - a fault while an exception is being entered stops the simulation
//!   (open);
//! - the non-maskable interrupt and the breakpoint register aren't there
//!   (open): `bkpt` holds what is written and does nothing.

use std::any::Any;

/// The status register's bits (RFC 0029, 2).
pub const SR_S: u32 = 1 << 31;
pub const SR_I: u32 = 1 << 30;
pub const SR_T: u32 = 1 << 29;
pub const SR_IPL_SHIFT: u32 = 24;

/// Where the exception vectors are: physical address 0, through the window.
pub const VEC_BASE: u32 = 0x8000_0000;
/// Vector offsets (RFC 0029, 6). Illegal, divide, address and tag are the
/// same offsets as on the machine without a supervisor.
pub const VEC_RESET: u32 = 0x00;
pub const VEC_BUS: u32 = 0x0C;
pub const VEC_PRIV: u32 = 0x1C;
pub const VEC_PAGE: u32 = 0x20;
pub const VEC_TRACE: u32 = 0x24;
pub const VEC_IRQ: u32 = 0x40;
pub const VEC_SWI: u32 = 0x100;

/// The page map: 128 contexts of 4096 pages of 4 KB (RFC 0029, 3).
pub const CONTEXTS: usize = 128;
pub const PAGES: usize = 4096;
pub const MAP_SIZE: usize = CONTEXTS * PAGES;
/// A map entry's bits.
pub const PTE_V: u32 = 1;
pub const PTE_W: u32 = 2;
pub const PTE_X: u32 = 4;
/// Bits 11-3 of an entry read as 0.
pub const PTE_MASK: u32 = 0xFFFF_F007;

/// `fsr`'s bits (RFC 0029, 3).
pub const FSR_INVALID: u32 = 1 << 0;
pub const FSR_NOWRITE: u32 = 1 << 1;
pub const FSR_NOEXEC: u32 = 1 << 2;
pub const FSR_RANGE: u32 = 1 << 3;
pub const FSR_WINDOW: u32 = 1 << 4;
pub const FSR_STORE: u32 = 1 << 5;
pub const FSR_FETCH: u32 = 1 << 6;
pub const FSR_SUPER: u32 = 1 << 7;

/// The translated space ends at 16 MB.
pub const TRANSLATED_TOP: u32 = 0x0100_0000;

/// Register banks, each r0-r15, HI and LO (RFC 0029, 5).
pub const BANKS: usize = 256;

/// What an access is for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Access {
    Load,
    Store,
    Fetch,
}

/// The board behind the CPU: the physical addresses RAM doesn't cover, and
/// the interrupt lines. Time is the machine's cycle count in its
/// reference configuration; the board turns it into its devices' time.
pub trait Bus: Any + Send + Sync {
    /// A read of `size` bytes (1, 2 or 4, aligned) at physical address
    /// `pa`, or None if nothing answers.
    fn read(&mut self, pa: u32, size: u32, cycles: u64) -> Option<u32>;
    /// A write; false if nothing answers.
    fn write(&mut self, pa: u32, size: u32, value: u32, cycles: u64) -> bool;
    /// The levels requesting an interrupt now (bit L for level L), and the
    /// cycle from which that may change without an access: u64::MAX if
    /// only an access can change it.
    fn irq(&mut self, cycles: u64) -> (u8, u64);
}

/// One bank: r0-r15, then HI and LO.
pub type Bank = [u32; 18];

/// The system state beside the user-visible machine.
pub struct Sys {
    pub ram_size: u32,
    pub bus: Box<dyn Bus>,
    /// S: supervisor mode.
    pub supervisor: bool,
    /// T: trace.
    pub t: u8,
    /// IPL, 0-15 as written; 8 and above hold off every level.
    pub ipl: u8,
    pub far: u32,
    pub fsr: u32,
    pub ctx: u32,
    pub mapa: u32,
    /// The bank user mode runs in, and MFUR and MTUR reach.
    pub bank: u32,
    pub bkpt: u32,
    pub map: Vec<u32>,
    /// Every bank but the one in use, which is the machine's registers.
    pub banks: Vec<Bank>,
    /// The bank the machine's registers are.
    pub cur_bank: usize,
    /// HALT with I set: waiting for an interrupt.
    pub waiting: bool,
    /// The levels requesting, as the bus last said, and when to ask again.
    pub irq_mask: u8,
    pub irq_next: u64,
    /// The PC's page, translated (the hardware's PC page register): the
    /// virtual page, the physical page, and whether it's valid.
    pub pc_vpage: u32,
    pub pc_ppage: u32,
    pub pc_valid: bool,
    /// Exceptions taken, by vector offset / 4 (SWIs all count at 0x40).
    pub exceptions: [u64; 0x41],
    pub interrupts: [u64; 8],
}

impl Sys {
    pub fn new(ram_size: u32, bus: Box<dyn Bus>) -> Sys {
        Sys {
            ram_size,
            bus,
            supervisor: true,
            t: 0,
            ipl: 0,
            far: 0,
            fsr: 0,
            ctx: 0,
            mapa: 0,
            bank: 0,
            bkpt: 0,
            map: vec![0; MAP_SIZE],
            banks: vec![[0; 18]; BANKS],
            cur_bank: 0,
            waiting: false,
            irq_mask: 0,
            irq_next: 0,
            pc_vpage: 0,
            pc_ppage: 0,
            pc_valid: false,
            exceptions: [0; 0x41],
            interrupts: [0; 8],
        }
    }

    /// Translate a virtual address, or say why it faults: the `fsr` bits
    /// (RFC 0029, 3).
    pub fn translate(&self, va: u32, acc: Access) -> Result<u32, u32> {
        let kind = match acc {
            Access::Load => 0,
            Access::Store => FSR_STORE,
            Access::Fetch => FSR_FETCH,
        } | if self.supervisor { FSR_SUPER } else { 0 };
        if va & 0x8000_0000 != 0 {
            if self.supervisor {
                return Ok(va & 0x7FFF_FFFF);
            }
            return Err(FSR_WINDOW | kind);
        }
        if va >= TRANSLATED_TOP {
            return Err(FSR_RANGE | kind);
        }
        let e = self.map[(self.ctx as usize) << 12 | (va >> 12) as usize];
        let why = if e & PTE_V == 0 {
            FSR_INVALID
        } else {
            match acc {
                Access::Store if e & PTE_W == 0 => FSR_NOWRITE,
                Access::Fetch if e & PTE_X == 0 => FSR_NOEXEC,
                _ => 0,
            }
        };
        if why != 0 {
            return Err(why | kind);
        }
        Ok((e & 0xFFFF_F000) | (va & 0xFFF))
    }

    /// Forget the PC's page (the map, ctx or the mode changed).
    pub fn forget_pc_page(&mut self) {
        self.pc_valid = false;
    }

    /// Ask the bus about the interrupt lines at the next boundary.
    pub fn touched(&mut self) {
        self.irq_next = 0;
    }

    /// The highest level requesting that IPL lets in, if any.
    pub fn pending(&self) -> Option<u32> {
        if self.irq_mask == 0 {
            return None;
        }
        let l = 7 - self.irq_mask.leading_zeros();
        (self.ipl <= 7 && l >= self.ipl as u32).then_some(l)
    }

    /// The board, as its own type.
    pub fn bus_as<B: Bus>(&mut self) -> Option<&mut B> {
        let b: &mut dyn Any = self.bus.as_mut();
        b.downcast_mut::<B>()
    }

    pub fn bus_ref<B: Bus>(&self) -> Option<&B> {
        let b: &dyn Any = self.bus.as_ref();
        b.downcast_ref::<B>()
    }
}
