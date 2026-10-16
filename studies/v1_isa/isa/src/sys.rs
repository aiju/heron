//! v1bs: draft 1b with the system extensions of the kernel study
//! (report 0020's appendix): a supervisor mode, register banks, the flat
//! page map of RFC 0010 and cross-mode loads and stores. Plain 1a and 1b
//! have none of this, and every machine runs exactly as before unless the
//! ISA is v1bs.
//!
//! - **Modes.** Reset is in supervisor mode. Traps and interrupts enter it;
//!   `RTI` restores the mode from the flags word it pops. User mode traps
//!   `HALT`, `EI`, `DI`, `RTI`, `MFUR`, `MTUR` and the special registers
//!   above `HI` (privilege vector, 0x1C), and `MTF` changes only N Z C V.
//! - **The flags word** gains S (bit 5), XL (bit 6) and XS (bit 7).
//! - **Stack pointers.** Without banks, `sp` is banked by the mode (the
//!   other one is `MFUR rd, sp` / `MTUR sp, rs` in supervisor mode). With
//!   full banks (`sysctl` = 1), supervisor mode has bank 0 all to itself
//!   (r1-r15 and HI) and user mode runs in bank `bank`. With half banks
//!   (`sysctl` = 2) only r8-r15 are banked that way, and r1-r7 and HI are
//!   shared, so a message in r1-r7 passes between threads untouched.
//! - **`SWI #n`** leaves n in `fsr`.
//! - **Translation.** User mode's fetches and data accesses go through the
//!   map: 16 contexts of 4096 entries, 4 KB pages, 16 MB per context. An
//!   entry is a physical page address (bits 31-12) and V, W, X (bits 0-2).
//!   Supervisor mode is untranslated, except data loads while XL is set
//!   and stores while XS is set, which go through the map as user
//!   accesses would (68010 `MOVES` with SFC/DFC, in two flag bits).
//! - **Faults** are precise: the page-fault vector (0x20) with the saved
//!   PC the faulting instruction's, `far` the address and `fsr` why.

use crate::insn::{Res, Stop, Trap};

pub const PRIV_VECTOR: u32 = 0x1C;
pub const PAGE_VECTOR: u32 = 0x20;

pub const PAGE_SHIFT: u32 = 12;
/// The virtual space of a context: 16 MB.
pub const USER_TOP: u32 = 1 << 24;
pub const CONTEXTS: usize = 16;
pub const PAGES: usize = (USER_TOP >> PAGE_SHIFT) as usize;
pub const BANKS: usize = 256;

/// Map entry bits.
pub const PTE_V: u32 = 1;
pub const PTE_W: u32 = 2;
pub const PTE_X: u32 = 4;

/// Fault status: why, and what kind of access.
pub const FSR_INVALID: u32 = 1;
pub const FSR_WRITE: u32 = 2;
pub const FSR_EXEC: u32 = 4;
pub const FSR_RANGE: u32 = 8;
pub const FSR_STORE: u32 = 0x10;
pub const FSR_FETCH: u32 = 0x20;
pub const FSR_CROSS: u32 = 0x40;

/// Special registers (MFSR/MTSR), after 0 (flags) and 1 (HI).
pub const SR_FAR: u8 = 2;
pub const SR_FSR: u8 = 3;
pub const SR_CTX: u8 = 4;
pub const SR_MAPA: u8 = 5;
pub const SR_MAPD: u8 = 6;
pub const SR_BANK: u8 = 7;
pub const SR_SYSCTL: u8 = 8;
pub const SR_LAST: u8 = 8;

/// sysctl: the banking policy, in bits 1-0
pub const SYSCTL_BANKS: u32 = 3;
/// no banks: only sp is banked, by the mode
pub const BANKS_NONE: u32 = 0;
/// full banks: r1-r15 and HI per bank, bank 0 the supervisor's
pub const BANKS_FULL: u32 = 1;
/// half banks: r8-r15 per bank, bank 0 the supervisor's; r1-r7 and HI
/// are shared by every bank
pub const BANKS_HALF: u32 = 2;

/// The flags word's system bits.
pub const FL_S: u32 = 1 << 5;
pub const FL_XL: u32 = 1 << 6;
pub const FL_XS: u32 = 1 << 7;

/// A memory access, for translation.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Acc {
    Fetch,
    Load,
    Store,
}

/// The system state of a v1bs machine.
pub struct Sys {
    /// supervisor mode
    pub s: u8,
    /// supervisor loads (XL) and stores (XS) go through the map
    pub xl: u8,
    pub xs: u8,
    /// the other mode's stack pointer (banks off)
    pub other_sp: u32,
    pub sysctl: u32,
    /// the user register bank (banks on)
    pub bank: u32,
    /// r0-r15 and HI of every bank but the active one; bank 0 is the
    /// supervisor's
    pub banks: Vec<[u32; 17]>,
    pub ctx: u32,
    pub mapa: u32,
    pub map: Vec<u32>,
    pub far: u32,
    pub fsr: u32,
    /// counters
    pub page_faults: u64,
    pub map_writes: u64,
    pub mode_switches: u64,
}

impl Default for Sys {
    fn default() -> Sys {
        Sys::new()
    }
}

impl Sys {
    pub fn new() -> Sys {
        Sys {
            s: 1,
            xl: 0,
            xs: 0,
            other_sp: 0,
            sysctl: 0,
            bank: 0,
            banks: vec![[0; 17]; BANKS],
            ctx: 0,
            mapa: 0,
            map: vec![0; CONTEXTS * PAGES],
            far: 0,
            fsr: 0,
            page_faults: 0,
            map_writes: 0,
            mode_switches: 0,
        }
    }

    pub fn banks_on(&self) -> bool {
        self.sysctl & SYSCTL_BANKS != BANKS_NONE
    }

    /// The first register a bank holds: 1 with full banks, 8 with half.
    pub fn first_banked(&self) -> usize {
        if self.sysctl & SYSCTL_BANKS == BANKS_HALF {
            8
        } else {
            1
        }
    }

    /// Whether a data access (not a fetch) is translated.
    #[inline]
    pub fn translates(&self, acc: Acc) -> bool {
        self.s == 0
            || match acc {
                Acc::Load => self.xl != 0,
                Acc::Store => self.xs != 0,
                Acc::Fetch => false,
            }
    }

    /// The physical address of a user access, or the fault status.
    pub fn xlate(&self, a: u32, acc: Acc) -> Result<u32, u32> {
        let kind = match acc {
            Acc::Fetch => FSR_FETCH,
            Acc::Load => 0,
            Acc::Store => FSR_STORE,
        } | if self.s != 0 { FSR_CROSS } else { 0 };
        if a >= USER_TOP {
            return Err(FSR_RANGE | kind);
        }
        let e = self.map[(self.ctx as usize) * PAGES + (a >> PAGE_SHIFT) as usize];
        if e & PTE_V == 0 {
            return Err(FSR_INVALID | kind);
        }
        if acc == Acc::Store && e & PTE_W == 0 {
            return Err(FSR_WRITE | kind);
        }
        if acc == Acc::Fetch && e & PTE_X == 0 {
            return Err(FSR_EXEC | kind);
        }
        Ok((e & !0xFFF) | (a & 0xFFF))
    }

    pub fn flag_bits(&self) -> u32 {
        (self.s as u32) << 5 | (self.xl as u32) << 6 | (self.xs as u32) << 7
    }
}

/// A page fault at address `a` with fault status `fsr`.
pub fn page_fault<T>(a: u32, fsr: u32) -> Res<T> {
    Err(Stop::Trap(Trap {
        vector: PAGE_VECTOR,
        fault: true,
        why: format!("page fault at {a:08X}"),
        page: Some((a, fsr)),
    }))
}

/// The special registers' names, for the assembler and disassembler.
pub const SR_NAMES: [&str; 9] = [
    "flags", "hi", "far", "fsr", "ctx", "mapa", "mapd", "bank", "sysctl",
];

use crate::insn::trap;
use crate::machine::{ILLEGAL_VECTOR, Machine};

impl Machine {
    /// In v1bs user mode.
    #[inline]
    pub fn user_mode(&self) -> bool {
        self.sys.as_ref().is_some_and(|s| s.s == 0)
    }

    /// Trap unless in supervisor mode (plain 1a and 1b have only that).
    pub fn privileged(&self) -> Res<()> {
        if self.user_mode() {
            return trap(PRIV_VECTOR, true, "privileged instruction");
        }
        Ok(())
    }

    /// S, XL and XS from a flags word, in supervisor mode.
    pub fn set_system_flags(&mut self, x: u32) {
        let sys = self.sys.as_mut().unwrap();
        sys.xl = (x & FL_XL != 0) as u8;
        sys.xs = (x & FL_XS != 0) as u8;
        if x & FL_S == 0 {
            self.to_user();
        }
    }

    /// Enter supervisor mode (traps and interrupts), with XL and XS off.
    pub fn to_supervisor(&mut self) {
        let sys = self.sys.as_mut().unwrap();
        sys.xl = 0;
        sys.xs = 0;
        if sys.s != 0 {
            return;
        }
        sys.s = 1;
        sys.mode_switches += 1;
        if sys.banks_on() {
            let b = sys.bank as usize;
            self.swap_bank(b, 0);
        } else {
            std::mem::swap(&mut self.r[15], &mut sys.other_sp);
        }
    }

    /// Enter user mode (RTI, or clearing S).
    pub fn to_user(&mut self) {
        let sys = self.sys.as_mut().unwrap();
        sys.xl = 0;
        sys.xs = 0;
        if sys.s == 0 {
            return;
        }
        sys.s = 0;
        sys.mode_switches += 1;
        if sys.banks_on() {
            let b = sys.bank as usize;
            self.swap_bank(0, b);
        } else {
            std::mem::swap(&mut self.r[15], &mut sys.other_sp);
        }
    }

    /// Put the active registers away as bank `from` and make bank `to`
    /// active (with half banks, only r8-r15).
    fn swap_bank(&mut self, from: usize, to: usize) {
        let sys = self.sys.as_mut().unwrap();
        let first = sys.first_banked();
        sys.banks[from][first..16].copy_from_slice(&self.r[first..]);
        self.r[first..].copy_from_slice(&sys.banks[to][first..16]);
        if first == 1 {
            sys.banks[from][16] = self.hi;
            self.hi = sys.banks[to][16];
        }
    }

    fn sys_or_illegal(&mut self) -> Res<&mut Sys> {
        match self.sys.as_deref_mut() {
            Some(s) => Ok(s),
            None => trap(ILLEGAL_VECTOR, true, "illegal instruction"),
        }
    }

    /// MFSR of a special register above HI.
    pub fn read_sr(&mut self, n: u8) -> Res<u32> {
        self.sys_or_illegal()?;
        self.privileged()?;
        let sys = self.sys.as_ref().unwrap();
        Ok(match n {
            SR_FAR => sys.far,
            SR_FSR => sys.fsr,
            SR_CTX => sys.ctx,
            SR_MAPA => sys.mapa,
            SR_MAPD => sys.map[sys.mapa as usize],
            SR_BANK => sys.bank,
            SR_SYSCTL => sys.sysctl,
            _ => return trap(ILLEGAL_VECTOR, true, "illegal instruction"),
        })
    }

    /// MTSR to a special register above HI.
    pub fn write_sr(&mut self, n: u8, v: u32) -> Res<()> {
        self.sys_or_illegal()?;
        self.privileged()?;
        if n > SR_LAST || n == SR_FAR || n == SR_FSR {
            return trap(ILLEGAL_VECTOR, true, "illegal instruction");
        }
        let sys = self.sys.as_mut().unwrap();
        match n {
            SR_CTX => sys.ctx = v % CONTEXTS as u32,
            SR_MAPA => sys.mapa = v % (CONTEXTS * PAGES) as u32,
            SR_MAPD => {
                sys.map[sys.mapa as usize] = v;
                sys.mapa = (sys.mapa + 1) % (CONTEXTS * PAGES) as u32;
                sys.map_writes += 1;
            }
            SR_BANK => sys.bank = v % BANKS as u32,
            _ => {
                // sysctl: switching banks on makes the active registers
                // the supervisor's bank (it is in supervisor mode)
                sys.sysctl = v & SYSCTL_BANKS;
            }
        }
        Ok(())
    }

    /// The user's register n, from supervisor mode (MFUR).
    pub fn user_reg(&mut self, n: u8) -> Res<u32> {
        let sys = self.sys_or_illegal()?;
        if n == 0 {
            return Ok(0);
        }
        Ok(if sys.banks_on() && n as usize >= sys.first_banked() {
            sys.banks[sys.bank as usize][n as usize]
        } else if n == 15 && !sys.banks_on() {
            sys.other_sp
        } else {
            self.r[n as usize]
        })
    }

    /// Set the user's register n, from supervisor mode (MTUR).
    pub fn set_user_reg(&mut self, n: u8, v: u32) -> Res<()> {
        let sys = self.sys_or_illegal()?;
        if n == 0 {
            return Ok(());
        }
        if sys.banks_on() && n as usize >= sys.first_banked() {
            let b = sys.bank as usize;
            sys.banks[b][n as usize] = v;
        } else if n == 15 && !sys.banks_on() {
            sys.other_sp = v;
        } else {
            self.r[n as usize] = v;
        }
        Ok(())
    }

    /// The physical address of a data access, translated if the mode and
    /// XL/XS say so.
    #[inline]
    pub fn data_phys(&mut self, a: u32, acc: Acc) -> Res<u32> {
        if let Some(p) = self.pages.as_deref_mut() {
            p.data(a, acc == Acc::Store);
        }
        match self.sys.as_deref() {
            Some(sys) if sys.translates(acc) => sys.xlate(a, acc).or_else(|fsr| page_fault(a, fsr)),
            _ => Ok(a),
        }
    }

    /// The physical address of an instruction fetch.
    #[inline]
    pub fn fetch_phys(&self, a: u32) -> Res<u32> {
        match self.sys.as_deref() {
            Some(sys) if sys.s == 0 => sys.xlate(a, Acc::Fetch).or_else(|fsr| page_fault(a, fsr)),
            _ => Ok(a),
        }
    }
}
