//! Decoded instructions and what they do (RFC 0028, 5).
//!
//! The decoder (decode.rs) turns the parcels at an address into an [`Insn`]
//! once; the machine executes it each time it comes round, which returns
//! the timing key or stops with a trap or an error. The flags, the ALU,
//! unary and shift functions are draft 1's, as RFC 0028 keeps them. A
//! machine without a supervisor has draft 1's interrupts
//! (reports/0004-rfc-draft-1-isa.md, 25); one made in system mode has RFC
//! 0029's ([`crate::sys`]): the system instructions here check the mode.
//! This module's shape is draft 1's too (studies/v1_isa/isa/src/insn.rs).

use crate::key::{Ea, How, Key, Kind};
use crate::machine::{ADDR_VECTOR, DIV_VECTOR, ILLEGAL_VECTOR, Machine, SWI_VECTOR, TAG_VECTOR};
use crate::sys::{
    BANKS, MAP_SIZE, MSG_MARK, PTE_MASK, SR_I, SR_IPL_SHIFT, SR_S, SR_T, VEC_PRIV, VEC_SWI,
};

/// An instruction trapping: `fault` saves the faulting instruction's
/// address, otherwise the next instruction's. In system mode `vector` is
/// the offset from the vector base, and `far` the address for `far` (a page
/// fault, a misaligned access or a bus error), with `fsr` the reason.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Trap {
    pub vector: u32,
    pub fault: bool,
    pub why: String,
    pub far: Option<u32>,
    pub fsr: u32,
}

/// Why an instruction didn't finish.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stop {
    Trap(Trap),
    /// The simulation can't go on: an unmapped access, a fetch outside RAM.
    Error(String),
    /// A read of the console with nothing waiting while its line is open
    /// (`Devices::open` in machine.rs): the instruction hasn't happened,
    /// and runs again once there is input.
    Wait,
}

pub type Res<T> = Result<T, Stop>;

pub fn trap<T>(vector: u32, fault: bool, why: &str) -> Res<T> {
    Err(Stop::Trap(Trap {
        vector,
        fault,
        why: why.into(),
        far: None,
        fsr: 0,
    }))
}

/// An instruction RFC 0028 leaves undefined: the hardware does whatever
/// it does, so the simulator stops rather than pick an answer.
pub fn undefined<T>(pc: u32, what: &str) -> Res<T> {
    Err(Stop::Error(format!(
        "undefined instruction at {pc:08X}: {what}"
    )))
}

pub fn misaligned<T>(what: &str, a: u32) -> Res<T> {
    Err(Stop::Trap(Trap {
        vector: ADDR_VECTOR,
        fault: true,
        why: format!("misaligned {what} at {a:08X}"),
        far: Some(a),
        fsr: 0,
    }))
}

/// A fault at an address, with `fsr` the reason: a page fault or a bus
/// error. Its text is made only when someone asks (trap_name).
pub fn fault_at<T>(vector: u32, a: u32, fsr: u32) -> Res<T> {
    Err(Stop::Trap(Trap {
        vector,
        fault: true,
        why: String::new(),
        far: Some(a),
        fsr,
    }))
}

/// A privileged instruction in user mode.
fn privileged<T>() -> Res<T> {
    Err(Stop::Trap(Trap {
        vector: VEC_PRIV,
        fault: true,
        why: String::new(),
        far: None,
        fsr: 0,
    }))
}

/// The link register: calls leave the return address in r7, and a return
/// is JMP r7.
pub const LINK: usize = 7;

fn illegal<T>() -> Res<T> {
    trap(ILLEGAL_VECTOR, true, "illegal instruction")
}

/// 1 if a and b differ in their upper 16 bits: a 16-bit datapath then
/// needs a second cycle for the address.
pub fn crosses(a: u32, b: u32) -> u8 {
    ((a ^ b) >> 16 != 0) as u8
}

/// Microcode steps for a shift by n: halves, then bytes, then bits.
pub fn shift_steps(n: u32) -> u32 {
    n / 16 + (n % 16) / 8 + n % 8
}

pub fn sext8(x: u32) -> u32 {
    x as u8 as i8 as i32 as u32
}

pub fn sext16(x: u32) -> u32 {
    x as u16 as i16 as i32 as u32
}

pub fn sext24(x: u32) -> u32 {
    ((x << 8) as i32 >> 8) as u32
}

fn bit_length(x: u32) -> u32 {
    32 - x.leading_zeros()
}

/// A memory operand: how the address is formed (`ea`), from which
/// registers and constants, and the access size.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MemOp {
    pub ea: Ea,
    pub base: u8,
    /// the displacement; for Abs and AbsX the address, for Pc and PcX the
    /// address too (the PC is known when decoding)
    pub disp: u32,
    pub index: u8,
    pub scale: u32,
    pub size: u8,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Insn {
    Illegal,
    Halt,
    Save {
        a: u8,
        cnt: u8,
    },
    Restore {
        a: u8,
        cnt: u8,
    },
    Rti,
    SetI {
        val: u8,
    },
    Mfsr {
        a: u8,
        b: u8,
    },
    Mtsr {
        a: u8,
        b: u8,
    },
    Swi {
        n: u8,
    },
    /// SPL #n: IPL <- n
    Spl {
        n: u8,
    },
    /// MFUR rd, rs: rd <- register rs of bank `bank`
    Mfur {
        d: u8,
        s: u8,
    },
    /// MTUR rd, rs: register rd of bank `bank` <- rs
    Mtur {
        d: u8,
        s: u8,
    },
    /// BCOPY rd, rs (tentative): r0-r7 of bank rs into bank rd
    Bcopy {
        d: u8,
        s: u8,
    },
    Set {
        a: u8,
        cc: u8,
    },
    /// rd <- f(rs), row D
    Unary {
        d: u8,
        s: u8,
        f: u8,
    },
    ShiftImm {
        d: u8,
        op: u8,
        cnt: u8,
    },
    ShiftReg {
        d: u8,
        s: u8,
        op: u8,
    },
    /// rd <- rd op rs
    AluReg {
        f: u8,
        d: u8,
        s: u8,
    },
    /// rd <- rd op #v
    AluImm {
        f: u8,
        d: u8,
        v: u32,
    },
    /// rd <- rd op memory
    AluMem {
        f: u8,
        d: u8,
        m: MemOp,
    },
    /// MOV from memory; `nz` sets N and Z from the value (MOVS)
    Load {
        d: u8,
        m: MemOp,
        nz: bool,
    },
    St {
        d: u8,
        m: MemOp,
    },
    LeaMem {
        d: u8,
        m: MemOp,
    },
    /// CLR on memory: store zero
    Clr {
        m: MemOp,
    },
    /// INC or DEC on memory
    IncMem {
        m: MemOp,
        dec: bool,
    },
    Bcc {
        cc: u8,
        target: u32,
    },
    Bsr {
        target: u32,
    },
    /// Jcc, JMP (cc 14) and CALL (cc 15) to a fixed target
    Jcc {
        cc: u8,
        target: u32,
        how: How,
    },
    /// DBNZ: r <- r - 1, and branch to target unless it reached zero
    Dbnz {
        r: u8,
        target: u32,
    },
    /// JMP and CALL to a register's value
    JeaReg {
        call: bool,
        rn: u8,
    },
    /// JMP and CALL to a constant
    JeaImm {
        call: bool,
        t: u32,
    },
    /// JMP and CALL to a word read from memory
    JeaMem {
        call: bool,
        m: MemOp,
    },
    /// LDM rb, ra-rc: cnt registers from a, loaded from [rb], [rb + 4], ...
    Ldm {
        b: u8,
        a: u8,
        cnt: u8,
    },
    /// STM rb, ra-rc
    Stm {
        b: u8,
        a: u8,
        cnt: u8,
    },
    /// MULA: r0:r1 <- r0:r1 + rd * rs, signed
    Mula {
        d: u8,
        s: u8,
    },
    /// MULFX: rd <- (rd * rs) >> n, signed
    Mulfx {
        d: u8,
        s: u8,
        n: u8,
    },
    /// The tagged operations: an ALU function on registers that traps
    /// (TAG_VECTOR) unless both operands (TMOV: the source) are integers,
    /// bit 0 clear, and TADD and TSUB on overflow too
    AluTag {
        f: u8,
        d: u8,
        rn: u8,
    },
}

/// The ALU functions.
pub const ALU_ADD: u8 = 0;
pub const ALU_ADC: u8 = 1;
pub const ALU_SUB: u8 = 2;
pub const ALU_SBC: u8 = 3;
pub const ALU_AND: u8 = 4;
pub const ALU_OR: u8 = 5;
pub const ALU_XOR: u8 = 6;
pub const ALU_BIC: u8 = 7;
/// MOVS: the value, setting N and Z.
pub const ALU_MOVS: u8 = 8;
pub const ALU_CMP: u8 = 9;
pub const ALU_TST: u8 = 10;
pub const ALU_MULU: u8 = 11;
pub const ALU_MULS: u8 = 12;
pub const ALU_DIVU: u8 = 13;
pub const ALU_DIVS: u8 = 14;
pub const ALU_DIVUL: u8 = 15;
/// MOV: the value, the flags left alone.
pub const ALU_MOV: u8 = 16;
/// ADD.B4: four bytes added on their own (tentative).
pub const ALU_ADDB4: u8 = 17;
/// MERGE: rs's bits where r0 has a 1, rd's elsewhere (tentative).
pub const ALU_MERGE: u8 = 18;

/// Whether ALU function f writes its result.
pub fn alu_writes(f: u8) -> bool {
    f != ALU_CMP && f != ALU_TST
}

/// The timing kind of ALU function f with second operand b.
pub fn alu_timing(f: u8, b: u32) -> Kind {
    match f {
        ALU_MULU => Kind::Mul {
            bits: bit_length(b),
            signed: 0,
        },
        ALU_MULS => Kind::Mul {
            bits: bit_length((b as i32).unsigned_abs()),
            signed: 1,
        },
        ALU_DIVU | ALU_DIVUL => Kind::Div { signed: 0 },
        ALU_DIVS => Kind::Div { signed: 1 },
        _ => Kind::Alu {
            wb: alu_writes(f) as u8,
        },
    }
}

impl Machine {
    fn nz(&mut self, res: u32) -> u32 {
        self.n = (res >> 31) as u8;
        self.z = (res == 0) as u8;
        res
    }

    fn add(&mut self, a: u32, b: u32, cin: u32) -> u32 {
        let r = a as u64 + b as u64 + cin as u64;
        let res = r as u32;
        self.c = (r >> 32) as u8;
        self.v = (((a ^ res) & (b ^ res)) >> 31) as u8;
        self.nz(res)
    }

    pub fn flags_word(&self) -> u32 {
        (self.v as u32)
            | (self.c as u32) << 1
            | (self.z as u32) << 2
            | (self.n as u32) << 3
            | (self.i as u32) << 4
    }

    /// The condition codes, `ccr`: `sr`'s byte 0.
    pub fn ccr(&self) -> u32 {
        (self.v as u32) | (self.c as u32) << 1 | (self.z as u32) << 2 | (self.n as u32) << 3
    }

    pub fn set_ccr(&mut self, x: u32) {
        self.v = (x & 1) as u8;
        self.c = ((x >> 1) & 1) as u8;
        self.z = ((x >> 2) & 1) as u8;
        self.n = ((x >> 3) & 1) as u8;
    }

    /// The status register (RFC 0029, 2), in system mode.
    pub fn sr(&self) -> u32 {
        let s = self.sys.as_ref().expect("system mode");
        self.ccr()
            | ((s.ipl as u32) << SR_IPL_SHIFT)
            | ((s.t as u32) * SR_T)
            | ((self.i as u32) * SR_I)
            | if s.supervisor { SR_S } else { 0 }
    }

    /// Set the status register but S, and the mode's other effects to
    /// follow it: what MTSR sr does (RFC 0029, 2: S is left alone).
    fn set_sr_but_s(&mut self, x: u32) {
        self.set_ccr(x);
        self.i = ((x & SR_I) != 0) as u8;
        let s = self.sys.as_mut().expect("system mode");
        s.t = ((x & SR_T) != 0) as u8;
        s.ipl = ((x >> SR_IPL_SHIFT) & 15) as u8;
    }

    /// Switch the registers to another bank: the ones in use go back to
    /// theirs.
    pub fn switch_bank(&mut self, to: usize) {
        let r = self.r;
        let s = self.sys.as_mut().expect("system mode");
        if s.cur_bank == to {
            return;
        }
        s.banks[s.cur_bank] = r;
        s.cur_bank = to;
        self.r = s.banks[to];
    }

    /// Set the mode: supervisor mode runs in bank 0, user mode in `bank`.
    fn set_mode(&mut self, supervisor: bool) {
        let s = self.sys.as_mut().expect("system mode");
        if s.supervisor != supervisor {
            s.supervisor = supervisor;
            s.forget_pc_page();
        }
        let to = if supervisor { 0 } else { s.bank as usize };
        self.switch_bank(to);
    }

    /// Register `n` of bank `bank`, which may be the one in use.
    fn user_reg(&self, n: usize) -> u32 {
        let s = self.sys.as_ref().expect("system mode");
        if s.bank as usize == s.cur_bank {
            self.r[n]
        } else {
            s.banks[s.bank as usize][n]
        }
    }

    fn set_user_reg(&mut self, n: usize, v: u32) {
        let s = self.sys.as_mut().expect("system mode");
        if s.bank as usize == s.cur_bank {
            self.r[n] = v;
        } else {
            s.banks[s.bank as usize][n] = v;
        }
    }

    /// In system mode, user mode traps a privileged instruction.
    fn check_privileged(&self) -> Res<()> {
        match &self.sys {
            Some(s) if !s.supervisor => privileged(),
            _ => Ok(()),
        }
    }

    pub fn set_flags_word(&mut self, x: u32) {
        self.v = (x & 1) as u8;
        self.c = ((x >> 1) & 1) as u8;
        self.z = ((x >> 2) & 1) as u8;
        self.n = ((x >> 3) & 1) as u8;
        self.i = ((x >> 4) & 1) as u8;
    }

    pub fn cond_true(&self, cc: u8) -> bool {
        let t = match cc >> 1 {
            0 => self.z,
            1 => self.c,
            2 => self.n,
            3 => self.v,
            4 => self.c & (self.z ^ 1),
            5 => (self.n == self.v) as u8,
            6 => (self.z ^ 1) & (self.n == self.v) as u8,
            _ => 1,
        };
        (t ^ (cc & 1)) != 0
    }

    /// ALU function f: the result, or None for "no write".
    fn alu(&mut self, f: u8, a: u32, b: u32) -> Res<Option<u32>> {
        Ok(Some(match f {
            ALU_ADD => self.add(a, b, 0),
            ALU_ADC => {
                let z = self.z;
                let r = self.add(a, b, self.c as u32);
                self.z &= z;
                r
            }
            ALU_SUB => self.add(a, !b, 1),
            ALU_SBC => {
                let z = self.z;
                let r = self.add(a, !b, self.c as u32);
                self.z &= z;
                r
            }
            ALU_AND => self.nz(a & b),
            ALU_OR => self.nz(a | b),
            ALU_XOR => self.nz(a ^ b),
            ALU_BIC => self.nz(a & !b),
            ALU_MOVS => self.nz(b),
            ALU_CMP => {
                self.add(a, !b, 1);
                return Ok(None);
            }
            ALU_TST => {
                self.nz(a & b);
                return Ok(None);
            }
            // The multiplies and divides put the high half or the remainder
            // in r0, after the operands are read and before the caller
            // writes rd, so rd wins where it is r0 (RFC 0028, 5.3).
            ALU_MULU => {
                let p = a as u64 * b as u64;
                self.r[0] = (p >> 32) as u32;
                let o = (p >> 32 != 0) as u8;
                (self.c, self.v) = (o, o);
                self.nz(p as u32)
            }
            ALU_MULS => {
                let p = a as i32 as i64 * b as i32 as i64;
                self.r[0] = (p >> 32) as u32;
                let o = (p != p as i32 as i64) as u8;
                (self.c, self.v) = (o, o);
                self.nz(p as u32)
            }
            ALU_DIVU => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                self.r[0] = a % b;
                (self.c, self.v) = (0, 0);
                self.nz(a / b)
            }
            ALU_DIVS => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                let (sa, sb) = (a as i32, b as i32);
                self.c = 0;
                if sa == i32::MIN && sb == -1 {
                    self.r[0] = 0;
                    self.v = 1;
                    return Ok(Some(self.nz(0x8000_0000)));
                }
                // truncating division, the remainder taking the dividend's sign
                let q = sa / sb;
                self.r[0] = sa.wrapping_sub(q.wrapping_mul(sb)) as u32;
                self.v = 0;
                self.nz(q as u32)
            }
            ALU_DIVUL => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                // r0:rd is the dividend; with r0 >= rs the quotient
                // wouldn't fit, and nothing but V changes
                let high = self.r[0];
                if high >= b {
                    self.v = 1;
                    return Ok(None);
                }
                let d = (high as u64) << 32 | a as u64;
                self.r[0] = (d % b as u64) as u32;
                (self.c, self.v) = (0, 0);
                self.nz((d / b as u64) as u32)
            }
            ALU_MOV => b,
            ALU_ADDB4 => {
                let lo7 = (a & 0x7F7F_7F7F).wrapping_add(b & 0x7F7F_7F7F);
                self.nz(lo7 ^ ((a ^ b) & 0x8080_8080))
            }
            // MERGE: the mask is r0
            _ => self.nz((a & !self.r[0]) | (b & self.r[0])),
        }))
    }

    /// Row D's functions, by column: NOT NEG INC DEC RLC RRC SWAP SXB SXH
    /// ZXB ZXH CLZ, and the tentative FFS POPC REV.
    fn unary(&mut self, f: u8, x: u32) -> u32 {
        match f {
            0 => self.nz(!x),
            1 => self.add(0, !x, 1),
            2 => self.nz(x.wrapping_add(1)),
            3 => self.nz(x.wrapping_sub(1)),
            4 => {
                let r = x << 1 | self.c as u32;
                self.c = (x >> 31) as u8;
                self.v = 0;
                self.nz(r)
            }
            5 => {
                let r = x >> 1 | (self.c as u32) << 31;
                self.c = (x & 1) as u8;
                self.v = 0;
                self.nz(r)
            }
            6 => self.nz(x.rotate_left(16)),
            7 => self.nz(sext8(x)),
            8 => self.nz(sext16(x)),
            9 => self.nz(x & 0xFF),
            10 => self.nz(x & 0xFFFF),
            11 => self.nz(x.leading_zeros()),
            12 => self.nz(x.trailing_zeros()),
            13 => self.nz(x.count_ones()),
            _ => self.nz(x.swap_bytes()),
        }
    }

    fn shift(&mut self, op: u8, x: u32, n: u32) -> u32 {
        let res = if n == 0 {
            x
        } else {
            match op {
                0 => {
                    self.c = ((x >> (32 - n)) & 1) as u8;
                    x << n
                }
                1 => {
                    self.c = ((x >> (n - 1)) & 1) as u8;
                    x >> n
                }
                2 => {
                    self.c = (((x as i32) >> (n - 1)) & 1) as u8;
                    ((x as i32) >> n) as u32
                }
                _ => {
                    let r = x.rotate_right(n);
                    self.c = (r >> 31) as u8;
                    r
                }
            }
        };
        self.v = 0;
        self.nz(res)
    }

    pub fn push(&mut self, v: u32) -> Res<()> {
        let sp = self.r[15].wrapping_sub(4);
        self.wr32(sp, v)?;
        self.r[15] = sp;
        Ok(())
    }

    pub fn pop(&mut self) -> Res<u32> {
        let sp = self.r[15];
        let v = self.rd32(sp)?;
        self.r[15] = sp.wrapping_add(4);
        Ok(v)
    }

    /// An interrupt or trap: push the PC and the flags, disable interrupts,
    /// jump to the vector.
    pub fn enter_interrupt(&mut self, vector: u32, ret: u32) -> Res<()> {
        let fl = self.flags_word();
        self.push(ret)?;
        self.push(fl)?;
        self.i = 0;
        self.pc = vector;
        Ok(())
    }

    /// Enter an exception in system mode (RFC 0029, 6): supervisor mode and
    /// bank 0, push the PC, then sr as it was, on bank 0's sp; clear I and
    /// T, set IPL for an interrupt; jump to the vector at `offset` from the
    /// base.
    pub fn enter_exception(&mut self, offset: u32, ret: u32, ipl: Option<u8>) -> Res<()> {
        let old = self.sr();
        self.set_mode(true);
        let sp = self.r[15];
        self.wr32(sp.wrapping_sub(4), ret)?;
        self.wr32(sp.wrapping_sub(8), old)?;
        self.r[15] = sp.wrapping_sub(8);
        self.i = 0;
        let s = self.sys.as_mut().expect("system mode");
        s.t = 0;
        if let Some(l) = ipl {
            s.ipl = l;
        }
        s.exceptions[(offset / 4).min(0x40) as usize] += 1;
        if old & SR_S == 0 {
            s.user_entries += 1;
        }
        self.pc = crate::sys::VEC_BASE.wrapping_add(offset);
        Ok(())
    }

    /// RTI in system mode: pop sr, then the PC, and with them the mode and
    /// the bank.
    fn rti_system(&mut self) -> Res<()> {
        let sp = self.r[15];
        let sr = self.rd32(sp)?;
        let pc = self.rd32(sp.wrapping_add(4))?;
        self.r[15] = sp.wrapping_add(8);
        self.set_sr_but_s(sr);
        self.set_mode(sr & SR_S != 0);
        self.pc = pc & !1;
        let cycles = self.cycles;
        let s = self.sys.as_mut().expect("system mode");
        if !s.supervisor
            && let Some(log) = &mut s.user_runs
            && log
                .iter()
                .rev()
                .find(|&&(_, b)| b & MSG_MARK == 0)
                .map(|&(_, b)| b as u32)
                != Some(s.bank)
        {
            log.push((cycles, s.bank as u16));
        }
        Ok(())
    }

    /// MFSR in system mode (RFC 0029, 4).
    fn mfsr_system(&mut self, n: u8) -> Res<u32> {
        if n >= 8 {
            self.check_privileged()?;
        }
        let s = self.sys.as_ref().expect("system mode");
        Ok(match n {
            0 => self.ccr(),
            8 => self.sr(),
            9 => s.far,
            10 => s.fsr,
            11 => s.ctx,
            12 => s.mapa,
            13 => s.map[s.mapa as usize],
            14 => s.bank,
            15 => s.bkpt,
            _ => 0,
        })
    }

    /// MTSR in system mode (RFC 0029, 4).
    fn mtsr_system(&mut self, n: u8, v: u32) -> Res<()> {
        if n >= 8 {
            self.check_privileged()?;
        }
        match n {
            0 => self.set_ccr(v),
            8 => self.set_sr_but_s(v),
            _ => {
                let s = self.sys.as_mut().expect("system mode");
                match n {
                    11 => {
                        s.ctx = v % crate::sys::CONTEXTS as u32;
                        s.forget_pc_page();
                    }
                    12 => s.mapa = v % MAP_SIZE as u32,
                    13 => {
                        s.map[s.mapa as usize] = v & PTE_MASK;
                        s.mapa = (s.mapa + 1) % MAP_SIZE as u32;
                        s.forget_pc_page();
                    }
                    14 => s.bank = v % BANKS as u32,
                    15 => s.bkpt = v,
                    // far and fsr are read only; 3-7 are reserved
                    _ => {}
                }
            }
        }
        Ok(())
    }

    /// A memory operand's address, and whether it carried.
    fn address(&self, m: &MemOp, nxt: u32) -> (u32, u8) {
        let r = |i: u8| self.r[i as usize];
        match m.ea {
            Ea::R | Ea::Pi => (r(m.base), 0),
            Ea::Rd => {
                let a = r(m.base).wrapping_add(m.disp);
                (a, crosses(r(m.base), a))
            }
            Ea::Abs => (m.disp, 0),
            Ea::Pc => (m.disp, crosses(nxt, m.disp)),
            Ea::Idx => {
                let a = r(m.base)
                    .wrapping_add(m.disp)
                    .wrapping_add(r(m.index).wrapping_mul(m.scale));
                (a, crosses(r(m.base), a))
            }
            Ea::Pd => {
                let a = r(m.base).wrapping_sub(m.size as u32);
                (a, crosses(r(m.base), a))
            }
            Ea::AbsX => (m.disp.wrapping_add(r(m.index).wrapping_mul(m.scale)), 0),
            Ea::PcX => (
                m.disp.wrapping_add(r(m.index).wrapping_mul(m.scale)),
                crosses(nxt, m.disp),
            ),
        }
    }

    /// Whether `d` is the register an auto-increment or -decrement steps,
    /// which RFC 0028 leaves undefined for an instruction with an `rd`.
    fn steps(m: &MemOp, d: u8) -> bool {
        matches!(m.ea, Ea::Pi | Ea::Pd) && m.base == d
    }

    /// The base register update after an auto-increment or -decrement.
    fn post(&mut self, m: &MemOp, a: u32) {
        match m.ea {
            Ea::Pi => self.r[m.base as usize] = a.wrapping_add(m.size as u32),
            Ea::Pd => self.r[m.base as usize] = a,
            _ => {}
        }
    }

    fn read(&mut self, size: u8, a: u32) -> Res<u32> {
        match size {
            4 => self.rd32(a),
            2 => self.rd16(a),
            _ => self.rd8(a),
        }
    }

    fn write(&mut self, size: u8, a: u32, v: u32) -> Res<()> {
        match size {
            4 => self.wr32(a, v),
            2 => self.wr16(a, v & 0xFFFF),
            _ => self.wr8(a, v & 0xFF),
        }
    }

    /// Execute an instruction of n parcels at pc: its timing key, or why
    /// it stopped.
    pub fn exec(&mut self, insn: Insn, pc: u32, n: u32) -> Res<Key> {
        let nxt = pc.wrapping_add(2 * n);
        let key = |kind| Key::new(n, pc, kind);
        let r = |m: &Machine, i: u8| m.r[i as usize];
        let jump = |call: bool, how: How, x: u8| {
            if call {
                Kind::Call { how, x }
            } else {
                Kind::Jmp { how, x }
            }
        };
        Ok(match insn {
            Insn::Illegal => return illegal(),
            Insn::Halt => {
                self.check_privileged()?;
                self.pc = nxt;
                match &mut self.sys {
                    // with I set, wait for an interrupt (RFC 0029, 7)
                    Some(s) if self.i != 0 => s.waiting = true,
                    _ => self.halted = true,
                }
                key(Kind::Sys)
            }
            Insn::Save { a, cnt } => {
                let sp = self.r[15].wrapping_sub(4 * cnt as u32);
                for i in 0..cnt {
                    self.wr32(sp.wrapping_add(4 * i as u32), r(self, a + i))?;
                }
                self.r[15] = sp;
                self.pc = nxt;
                key(Kind::Save { n: cnt })
            }
            Insn::Restore { a, cnt } => {
                let sp = self.r[15];
                let mut vals = [0u32; 16];
                for i in 0..cnt {
                    vals[i as usize] = self.rd32(sp.wrapping_add(4 * i as u32))?;
                }
                for i in 0..cnt {
                    self.r[(a + i) as usize] = vals[i as usize];
                }
                self.r[15] = sp.wrapping_add(4 * cnt as u32);
                self.pc = nxt;
                key(Kind::Restore { n: cnt })
            }
            Insn::Rti => {
                if self.sys.is_some() {
                    self.check_privileged()?;
                    self.rti_system()?;
                } else {
                    let fl = self.pop()?;
                    self.set_flags_word(fl);
                    self.pc = self.pop()? & !1;
                }
                key(Kind::Rti)
            }
            Insn::SetI { val } => {
                self.check_privileged()?;
                self.i = val;
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Mfsr { a, b } => {
                let v = if self.sys.is_some() {
                    self.mfsr_system(b)?
                } else {
                    match b {
                        0 => self.flags_word(),
                        _ => return illegal(),
                    }
                };
                self.r[a as usize] = v;
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Mtsr { a, b } => {
                if self.sys.is_some() {
                    self.mtsr_system(a, r(self, b))?;
                } else {
                    match a {
                        0 => self.set_flags_word(r(self, b)),
                        _ => return illegal(),
                    }
                }
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Swi { n } => {
                self.pc = nxt;
                if self.sys.is_some() {
                    return Err(Stop::Trap(Trap {
                        vector: VEC_SWI + 4 * n as u32,
                        fault: false,
                        why: String::new(),
                        far: None,
                        fsr: 0,
                    }));
                }
                return trap(SWI_VECTOR, false, "SWI");
            }
            Insn::Spl { n } => {
                if self.sys.is_none() {
                    return illegal();
                }
                self.check_privileged()?;
                self.sys.as_mut().unwrap().ipl = n;
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Mfur { d, s } => {
                if self.sys.is_none() {
                    return illegal();
                }
                self.check_privileged()?;
                self.r[d as usize] = self.user_reg(s as usize);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Mtur { d, s } => {
                if self.sys.is_none() {
                    return illegal();
                }
                self.check_privileged()?;
                let v = r(self, s);
                self.set_user_reg(d as usize, v);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Bcopy { d, s } => {
                if self.sys.is_none() {
                    return illegal();
                }
                self.check_privileged()?;
                let (to, from) = (r(self, d) as usize % BANKS, r(self, s) as usize % BANKS);
                let cur = self.sys.as_ref().unwrap().cur_bank;
                let mut vals = [0u32; 8];
                if from == cur {
                    vals.copy_from_slice(&self.r[..8]);
                } else {
                    vals.copy_from_slice(&self.sys.as_ref().unwrap().banks[from][..8]);
                }
                let cycles = self.cycles;
                if let Some(log) = &mut self.sys.as_mut().unwrap().user_runs {
                    log.push((cycles, MSG_MARK | to as u16));
                }
                if to == cur {
                    self.r[..8].copy_from_slice(&vals);
                } else {
                    self.sys.as_mut().unwrap().banks[to][..8].copy_from_slice(&vals);
                }
                self.pc = nxt;
                key(Kind::Bcopy { n: 8 })
            }
            Insn::Set { a, cc } => {
                self.r[a as usize] = self.cond_true(cc) as u32;
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Unary { d, s, f } => {
                self.r[d as usize] = self.unary(f, r(self, s));
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::ShiftImm { d, op, cnt } => {
                self.r[d as usize] = self.shift(op, r(self, d), cnt as u32);
                self.pc = nxt;
                key(Kind::Shift {
                    steps: shift_steps(cnt as u32),
                })
            }
            Insn::ShiftReg { d, s, op } => {
                let cnt = r(self, s) & 31;
                self.r[d as usize] = self.shift(op, r(self, d), cnt);
                self.pc = nxt;
                key(Kind::Shift {
                    steps: shift_steps(cnt),
                })
            }
            Insn::AluReg { f, d, s } => {
                let b = r(self, s);
                if let Some(v) = self.alu(f, r(self, d), b)? {
                    self.r[d as usize] = v;
                }
                self.pc = nxt;
                key(alu_timing(f, b))
            }
            Insn::AluImm { f, d, v } => {
                if let Some(res) = self.alu(f, r(self, d), v)? {
                    self.r[d as usize] = res;
                }
                self.pc = nxt;
                key(alu_timing(f, v))
            }
            Insn::AluMem { f, d, m } => {
                if Self::steps(&m, d) {
                    return undefined(pc, "rd is the register its mode steps");
                }
                let (a, x) = self.address(&m, nxt);
                let v = self.read(m.size, a)?;
                self.post(&m, a);
                if let Some(res) = self.alu(f, r(self, d), v)? {
                    self.r[d as usize] = res;
                }
                self.pc = nxt;
                key(match alu_timing(f, v) {
                    Kind::Alu { wb } => Kind::Op {
                        ea: m.ea,
                        size: m.size,
                        x,
                        wb,
                    },
                    // MULU or MULS with a word from memory: the multiply
                    // (the load isn't costed)
                    k => k,
                })
            }
            Insn::Load { d, m, nz } => {
                if Self::steps(&m, d) {
                    return undefined(pc, "rd is the register its mode steps");
                }
                let (a, x) = self.address(&m, nxt);
                let v = self.read(m.size, a)?;
                self.post(&m, a);
                if nz {
                    // N from the operand's own top bit: bit 7 of a byte
                    self.n = ((v >> (8 * m.size as u32 - 1)) & 1) as u8;
                    self.z = (v == 0) as u8;
                }
                self.r[d as usize] = v;
                self.pc = nxt;
                key(Kind::Ld {
                    ea: m.ea,
                    size: m.size,
                    x,
                })
            }
            Insn::St { d, m } => {
                let v = r(self, d);
                let (a, x) = self.address(&m, nxt);
                self.write(m.size, a, v)?;
                self.post(&m, a);
                self.pc = nxt;
                key(Kind::St {
                    ea: m.ea,
                    size: m.size,
                    x,
                })
            }
            Insn::LeaMem { d, m } => {
                let (a, x) = self.address(&m, nxt);
                self.r[d as usize] = a;
                self.pc = nxt;
                key(Kind::Lea { ea: m.ea, x })
            }
            Insn::Clr { m } => {
                let (a, x) = self.address(&m, nxt);
                self.write(m.size, a, 0)?;
                self.post(&m, a);
                self.pc = nxt;
                key(Kind::St {
                    ea: m.ea,
                    size: m.size,
                    x,
                })
            }
            Insn::IncMem { m, dec } => {
                let (a, x) = self.address(&m, nxt);
                let v = self.read(m.size, a)?;
                let bits = 8 * m.size as u32;
                let mask = if bits == 32 {
                    u32::MAX
                } else {
                    (1 << bits) - 1
                };
                let res = if dec {
                    v.wrapping_sub(1)
                } else {
                    v.wrapping_add(1)
                } & mask;
                // N and Z of the value as stored: a byte or half's own sign
                self.n = ((res >> (bits - 1)) & 1) as u8;
                self.z = (res == 0) as u8;
                self.write(m.size, a, res)?;
                self.post(&m, a);
                self.pc = nxt;
                key(Kind::Rmw {
                    ea: m.ea,
                    size: m.size,
                    x,
                })
            }
            Insn::Bcc { cc, target } => {
                if self.cond_true(cc) {
                    self.pc = target;
                    key(Kind::Br {
                        taken: 1,
                        x: crosses(nxt, target),
                    })
                } else {
                    self.pc = nxt;
                    key(Kind::Br { taken: 0, x: 0 })
                }
            }
            Insn::Bsr { target } => {
                self.r[LINK] = nxt;
                self.pc = target;
                key(Kind::Call {
                    how: How::Rel,
                    x: crosses(nxt, target),
                })
            }
            Insn::Jcc { cc, target, how } => {
                let x = if how == How::Rel {
                    crosses(nxt, target)
                } else {
                    0
                };
                if cc == 15 {
                    self.r[LINK] = nxt;
                    self.pc = target;
                    key(Kind::Call { how, x })
                } else if cc == 14 || self.cond_true(cc) {
                    self.pc = target;
                    key(Kind::Jmp { how, x })
                } else {
                    self.pc = nxt;
                    key(Kind::Br { taken: 0, x: 0 })
                }
            }
            Insn::Dbnz { r: rn, target } => {
                let v = r(self, rn).wrapping_sub(1);
                self.r[rn as usize] = v;
                if v != 0 {
                    self.pc = target;
                    key(Kind::Dbnz {
                        taken: 1,
                        x: crosses(nxt, target),
                    })
                } else {
                    self.pc = nxt;
                    key(Kind::Dbnz { taken: 0, x: 0 })
                }
            }
            Insn::JeaReg { call, rn } => {
                let t = r(self, rn) & !1;
                if call {
                    self.r[LINK] = nxt;
                }
                self.pc = t;
                key(jump(call, How::Reg, 0))
            }
            Insn::JeaImm { call, t } => {
                if call {
                    self.r[LINK] = nxt;
                }
                self.pc = t;
                key(jump(call, How::Abs, 0))
            }
            Insn::JeaMem { call, m } => {
                let (a, x) = self.address(&m, nxt);
                let t = self.rd32(a)? & !1;
                self.post(&m, a);
                if call {
                    self.r[LINK] = nxt;
                }
                self.pc = t;
                let ea = m.ea;
                key(if call {
                    Kind::Callm { ea, x }
                } else {
                    Kind::Jmpm { ea, x }
                })
            }
            Insn::Ldm { b, a, cnt } => {
                if (a..a + cnt).contains(&b) {
                    return undefined(pc, "LDM's range holds its base register");
                }
                let base = r(self, b);
                let mut vals = [0u32; 16];
                for i in 0..cnt {
                    vals[i as usize] = self.rd32(base.wrapping_add(4 * i as u32))?;
                }
                for i in 0..cnt {
                    self.r[(a + i) as usize] = vals[i as usize];
                }
                self.pc = nxt;
                key(Kind::Ldm { n: cnt })
            }
            Insn::Stm { b, a, cnt } => {
                let base = r(self, b);
                for i in 0..cnt {
                    self.wr32(base.wrapping_add(4 * i as u32), r(self, a + i))?;
                }
                self.pc = nxt;
                key(Kind::Stm { n: cnt })
            }
            Insn::Mula { d, s } => {
                let b = r(self, s);
                let p = r(self, d) as i32 as i64 * b as i32 as i64;
                // r0:r1 is the accumulator
                let acc = ((self.r[0] as u64) << 32 | self.r[1] as u64).wrapping_add(p as u64);
                (self.r[0], self.r[1]) = ((acc >> 32) as u32, acc as u32);
                self.pc = nxt;
                // a multiply, and two more ALU passes for the 64-bit add
                key(Kind::Mul {
                    bits: bit_length((b as i32).unsigned_abs()) + 2,
                    signed: 1,
                })
            }
            Insn::Mulfx { d, s, n: sh } => {
                let b = r(self, s);
                let p = r(self, d) as i32 as i64 * b as i32 as i64;
                // r0 gets the product's high half, then rd the result
                self.r[0] = (p >> 32) as u32;
                let q = p >> sh;
                let o = (q != q as i32 as i64) as u8;
                (self.c, self.v) = (o, o);
                self.r[d as usize] = self.nz(q as u32);
                self.pc = nxt;
                // a multiply, then the 64-bit product shifted: each step of
                // the shift is a pass over both halves
                key(Kind::Mul {
                    bits: bit_length((b as i32).unsigned_abs()) + 2 * shift_steps(sh as u32),
                    signed: 1,
                })
            }
            Insn::AluTag { f, d, rn } => {
                let (a, b) = (r(self, d), r(self, rn));
                let checked = if f == ALU_MOV { b } else { a | b };
                if checked & 1 != 0 {
                    return trap(TAG_VECTOR, true, "tag check");
                }
                let ov = match f {
                    ALU_ADD => (a as i32).checked_add(b as i32).is_none(),
                    ALU_SUB => (a as i32).checked_sub(b as i32).is_none(),
                    _ => false,
                };
                if ov {
                    return trap(TAG_VECTOR, true, "tagged overflow");
                }
                if let Some(v) = self.alu(f, a, b)? {
                    self.r[d as usize] = v;
                }
                self.pc = nxt;
                key(Kind::Alu {
                    wb: alu_writes(f) as u8,
                })
            }
        })
    }
}
