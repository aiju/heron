//! Decoded instructions and what they do: the semantics drafts 1a and 1b
//! share (studies/v1_isa/v1common.py and isa-v1.md).
//!
//! A decoder turns the parcels at an address into an [`Insn`] once; the
//! machine executes it each time it comes round, which returns the timing
//! key or stops with a trap or an error.

use crate::key::{Ea, How, Key, Kind};
use crate::machine::{ADDR_VECTOR, DIV_VECTOR, ILLEGAL_VECTOR, Machine, SWI_VECTOR, TAG_VECTOR};

/// An instruction trapping: `fault` saves the faulting instruction's
/// address, otherwise the next instruction's.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Trap {
    pub vector: u32,
    pub fault: bool,
    pub why: String,
}

/// Why an instruction didn't finish.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stop {
    Trap(Trap),
    /// The simulation can't go on: an unmapped access, a fetch outside RAM.
    Error(String),
}

pub type Res<T> = Result<T, Stop>;

pub fn trap<T>(vector: u32, fault: bool, why: &str) -> Res<T> {
    Err(Stop::Trap(Trap {
        vector,
        fault,
        why: why.into(),
    }))
}

pub fn misaligned<T>(what: &str, a: u32) -> Res<T> {
    trap(ADDR_VECTOR, true, &format!("misaligned {what} at {a:08X}"))
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

fn bit_length(x: u32) -> u32 {
    32 - x.leading_zeros()
}

/// A memory operand of draft 1b: how the address is formed (`ea`), from
/// which registers and constants, and the access size.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MemOp {
    pub ea: Ea,
    pub base: u8,
    /// the displacement; for Abs the address, for Pc the address too (the
    /// PC is known when decoding)
    pub disp: u32,
    pub index: u8,
    pub scale: u32,
    pub size: u8,
}

/// A load or store of draft 1a.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Access {
    pub load: bool,
    pub size: u8,
    pub signed: bool,
    pub d: u8,
    pub s: u8,
    pub disp: u32,
    /// Rd, Rd32 or Abs: only Rd counts an address carry
    pub ea: Ea,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Insn {
    Illegal,
    Halt,
    Nop,
    JmpReg {
        b: u8,
    },
    CallReg {
        b: u8,
    },
    Ret,
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
    Swi,
    Set {
        a: u8,
        cc: u8,
    },
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
    AluRR {
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
    // ---- draft 1a
    /// ADDI: rd <- rd + v, setting N and Z only
    AddI {
        d: u8,
        v: u32,
    },
    Access(Access),
    /// LEA rd, [rs + disp]
    Lea {
        d: u8,
        s: u8,
        disp: u32,
        ea: Ea,
    },
    /// LEA rd, [pc + disp]: the address is known when decoding
    LeaConst {
        d: u8,
        a: u32,
    },
    // ---- draft 1b
    JeaReg {
        call: bool,
        rn: u8,
    },
    JeaImm {
        call: bool,
        t: u32,
    },
    JeaMem {
        call: bool,
        m: MemOp,
    },
    St {
        d: u8,
        m: MemOp,
    },
    LeaMem {
        d: u8,
        m: MemOp,
    },
    /// MOV and the ALU operations on a register
    AluReg {
        f: u8,
        d: u8,
        rn: u8,
    },
    /// MOV from memory
    Load {
        d: u8,
        m: MemOp,
    },
    /// an ALU operation on a memory operand
    AluMem {
        f: u8,
        d: u8,
        m: MemOp,
    },
    // ---- v1bx
    /// MOV or an ALU operation on a tagged register: as on a register,
    /// but it traps (TAG_VECTOR) unless both operands (MOV: the source)
    /// have bit 0 clear, and ADD and SUB trap on overflow
    AluTag {
        f: u8,
        d: u8,
        rn: u8,
    },
}

/// ALU function numbers (v1common.ALU_FN).
pub const ALU_CMP: u8 = 9;
pub const ALU_TST: u8 = 10;
pub const ALU_MOV: u8 = 8;

/// Whether ALU function f writes its result.
pub fn alu_writes(f: u8) -> bool {
    f != ALU_CMP && f != ALU_TST
}

/// The timing kind of ALU function f with second operand b.
pub fn alu_timing(f: u8, b: u32) -> Kind {
    match f {
        11 => Kind::Mul {
            bits: bit_length(b),
            signed: 0,
        },
        12 => Kind::Mul {
            bits: bit_length((b as i32).unsigned_abs()),
            signed: 1,
        },
        13 | 15 => Kind::Div { signed: 0 },
        14 => Kind::Div { signed: 1 },
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
            0 => self.add(a, b, 0),
            1 => {
                let z = self.z;
                let r = self.add(a, b, self.c as u32);
                self.z &= z;
                r
            }
            2 => self.add(a, !b, 1),
            3 => {
                let z = self.z;
                let r = self.add(a, !b, self.c as u32);
                self.z &= z;
                r
            }
            4 => self.nz(a & b),
            5 => self.nz(a | b),
            6 => self.nz(a ^ b),
            7 => self.nz(a & !b),
            8 => self.nz(b),
            9 => {
                self.add(a, !b, 1);
                return Ok(None);
            }
            10 => {
                self.nz(a & b);
                return Ok(None);
            }
            11 => {
                let p = a as u64 * b as u64;
                self.hi = (p >> 32) as u32;
                let o = (self.hi != 0) as u8;
                (self.c, self.v) = (o, o);
                self.nz(p as u32)
            }
            12 => {
                let p = a as i32 as i64 * b as i32 as i64;
                self.hi = (p >> 32) as u32;
                let o = (p != p as i32 as i64) as u8;
                (self.c, self.v) = (o, o);
                self.nz(p as u32)
            }
            13 => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                self.hi = a % b;
                (self.c, self.v) = (0, 0);
                self.nz(a / b)
            }
            14 => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                let (sa, sb) = (a as i32, b as i32);
                self.c = 0;
                if sa == i32::MIN && sb == -1 {
                    self.hi = 0;
                    self.v = 1;
                    return Ok(Some(self.nz(0x8000_0000)));
                }
                // truncating division, the remainder taking the dividend's sign
                let q = sa / sb;
                self.hi = sa.wrapping_sub(q.wrapping_mul(sb)) as u32;
                self.v = 0;
                self.nz(q as u32)
            }
            _ => {
                if b == 0 {
                    return trap(DIV_VECTOR, true, "divide by zero");
                }
                if self.hi >= b {
                    self.v = 1;
                    return Ok(None);
                }
                let d = (self.hi as u64) << 32 | a as u64;
                self.hi = (d % b as u64) as u32;
                (self.c, self.v) = (0, 0);
                self.nz((d / b as u64) as u32)
            }
        }))
    }

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
            8 => self.nz(x & 0xFF),
            9 => self.nz(sext16(x)),
            10 => self.nz(x & 0xFFFF),
            _ => self.nz(x.leading_zeros()),
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
        self.push(ret)?;
        self.push(self.flags_word())?;
        self.i = 0;
        self.pc = vector;
        Ok(())
    }

    fn set_reg(&mut self, d: u8, v: u32) {
        if d != 0 {
            self.r[d as usize] = v;
        }
    }

    /// A draft 1b memory operand's address, and whether it carried.
    fn address(&self, m: &MemOp, nxt: u32) -> (u32, u8) {
        let r = |i: u8| self.r[i as usize];
        match m.ea {
            Ea::R | Ea::Pi => (r(m.base), 0),
            Ea::Rd | Ea::Rd32 => {
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
        }
    }

    /// The base register update after an auto-increment or -decrement.
    fn post(&mut self, m: &MemOp, a: u32) {
        match m.ea {
            Ea::Pi => self.set_reg(m.base, a.wrapping_add(m.size as u32)),
            Ea::Pd => self.set_reg(m.base, a),
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
        Ok(match insn {
            Insn::Illegal => return trap(ILLEGAL_VECTOR, true, "illegal instruction"),
            Insn::Halt => {
                self.halted = true;
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Nop => {
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::JmpReg { b } => {
                self.pc = r(self, b) & !1;
                key(Kind::Jmp {
                    how: How::Reg,
                    x: 0,
                })
            }
            Insn::CallReg { b } => {
                let t = r(self, b) & !1;
                self.push(nxt)?;
                self.pc = t;
                key(Kind::Call {
                    how: How::Reg,
                    x: 0,
                })
            }
            Insn::Ret => {
                self.pc = self.pop()? & !1;
                key(Kind::Ret)
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
                let fl = self.pop()?;
                self.set_flags_word(fl);
                self.pc = self.pop()? & !1;
                key(Kind::Rti)
            }
            Insn::SetI { val } => {
                self.i = val;
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Mfsr { a, b } => {
                let v = if b == 0 { self.flags_word() } else { self.hi };
                self.set_reg(a, v);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Mtsr { a, b } => {
                if a == 0 {
                    self.set_flags_word(r(self, b));
                } else {
                    self.hi = r(self, b);
                }
                self.pc = nxt;
                key(Kind::Sys)
            }
            Insn::Swi => {
                self.pc = nxt;
                return trap(SWI_VECTOR, false, "SWI");
            }
            Insn::Set { a, cc } => {
                let v = self.cond_true(cc) as u32;
                self.set_reg(a, v);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Unary { d, s, f } => {
                let v = self.unary(f, r(self, s));
                self.set_reg(d, v);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::ShiftImm { d, op, cnt } => {
                let v = self.shift(op, r(self, d), cnt as u32);
                self.set_reg(d, v);
                self.pc = nxt;
                key(Kind::Shift {
                    steps: shift_steps(cnt as u32),
                })
            }
            Insn::ShiftReg { d, s, op } => {
                let cnt = r(self, s) & 31;
                let v = self.shift(op, r(self, d), cnt);
                self.set_reg(d, v);
                self.pc = nxt;
                key(Kind::Shift {
                    steps: shift_steps(cnt),
                })
            }
            Insn::AluRR { f, d, s } => {
                let b = r(self, s);
                if let Some(v) = self.alu(f, r(self, d), b)? {
                    self.set_reg(d, v);
                }
                self.pc = nxt;
                key(alu_timing(f, b))
            }
            Insn::AluImm { f, d, v } => {
                if let Some(res) = self.alu(f, r(self, d), v)? {
                    self.set_reg(d, res);
                }
                self.pc = nxt;
                key(alu_timing(f, v))
            }
            Insn::Bcc { cc, target } => {
                let x = crosses(nxt, target);
                if self.cond_true(cc) {
                    self.pc = target;
                    key(Kind::Br { taken: 1, x })
                } else {
                    self.pc = nxt;
                    key(Kind::Br { taken: 0, x: 0 })
                }
            }
            Insn::Bsr { target } => {
                self.push(nxt)?;
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
                    self.push(nxt)?;
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
            Insn::AddI { d, v } => {
                let res = self.nz(r(self, d).wrapping_add(v));
                self.set_reg(d, res);
                self.pc = nxt;
                key(Kind::Alu { wb: 1 })
            }
            Insn::Access(acc) => {
                let base = r(self, acc.s);
                let a = base.wrapping_add(acc.disp);
                if acc.load {
                    let mut v = self.read(acc.size, a)?;
                    if acc.signed {
                        v = if acc.size == 2 { sext16(v) } else { sext8(v) };
                    }
                    self.nz(v);
                    self.set_reg(acc.d, v);
                } else {
                    let v = r(self, acc.d);
                    self.write(acc.size, a, v)?;
                }
                self.pc = nxt;
                let x = if acc.ea == Ea::Rd {
                    crosses(base, a)
                } else {
                    0
                };
                let (ea, size) = (acc.ea, acc.size);
                key(if acc.load {
                    Kind::Ld { ea, size, x }
                } else {
                    Kind::St { ea, size, x }
                })
            }
            Insn::Lea { d, s, disp, ea } => {
                let base = r(self, s);
                let a = base.wrapping_add(disp);
                self.set_reg(d, a);
                self.pc = nxt;
                key(Kind::Lea {
                    ea,
                    x: if ea == Ea::Rd { crosses(base, a) } else { 0 },
                })
            }
            Insn::LeaConst { d, a } => {
                self.set_reg(d, a);
                self.pc = nxt;
                key(Kind::Lea {
                    ea: Ea::Pc,
                    x: crosses(nxt, a),
                })
            }
            Insn::JeaReg { call, rn } => {
                let t = r(self, rn) & !1;
                if call {
                    self.push(nxt)?;
                }
                self.pc = t;
                let how = How::Reg;
                key(if call {
                    Kind::Call { how, x: 0 }
                } else {
                    Kind::Jmp { how, x: 0 }
                })
            }
            Insn::JeaImm { call, t } => {
                if call {
                    self.push(nxt)?;
                }
                self.pc = t;
                let how = How::Abs;
                key(if call {
                    Kind::Call { how, x: 0 }
                } else {
                    Kind::Jmp { how, x: 0 }
                })
            }
            Insn::JeaMem { call, m } => {
                let (a, x) = self.address(&m, nxt);
                let t = self.rd32(a)? & !1;
                self.post(&m, a);
                if call {
                    self.push(nxt)?;
                }
                self.pc = t;
                let ea = m.ea;
                key(if call {
                    Kind::Callm { ea, x }
                } else {
                    Kind::Jmpm { ea, x }
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
                self.set_reg(d, a);
                self.pc = nxt;
                key(Kind::Lea { ea: m.ea, x })
            }
            Insn::AluReg { f, d, rn } => {
                if let Some(v) = self.alu(f, r(self, d), r(self, rn))? {
                    self.set_reg(d, v);
                }
                self.pc = nxt;
                key(Kind::Alu {
                    wb: alu_writes(f) as u8,
                })
            }
            Insn::Load { d, m } => {
                let (a, x) = self.address(&m, nxt);
                let v = self.read(m.size, a)?;
                self.post(&m, a);
                self.nz(v);
                self.set_reg(d, v);
                self.pc = nxt;
                key(Kind::Ld {
                    ea: m.ea,
                    size: m.size,
                    x,
                })
            }
            Insn::AluTag { f, d, rn } => {
                let (a, b) = (r(self, d), r(self, rn));
                if (if f == ALU_MOV { b } else { a | b }) & 1 != 0 {
                    return trap(TAG_VECTOR, true, "tag check");
                }
                let ov = match f {
                    0 => (a as i32).checked_add(b as i32).is_none(),
                    2 => (a as i32).checked_sub(b as i32).is_none(),
                    _ => false,
                };
                if ov {
                    return trap(TAG_VECTOR, true, "tagged overflow");
                }
                if let Some(v) = self.alu(f, a, b)? {
                    self.set_reg(d, v);
                }
                self.pc = nxt;
                key(Kind::Alu {
                    wb: alu_writes(f) as u8,
                })
            }
            Insn::AluMem { f, d, m } => {
                let (a, x) = self.address(&m, nxt);
                let v = self.read(m.size, a)?;
                self.post(&m, a);
                if let Some(res) = self.alu(f, r(self, d), v)? {
                    self.set_reg(d, res);
                }
                self.pc = nxt;
                key(Kind::Op {
                    ea: m.ea,
                    size: m.size,
                    x,
                    wb: alu_writes(f) as u8,
                })
            }
        })
    }
}

// ---------------------------------------------------------------- shared decoders

/// The system group (major opcode 0 in both drafts).
pub fn dec_sys(w: u32) -> Insn {
    let (a, b, f) = (((w >> 8) & 15) as u8, ((w >> 4) & 15) as u8, (w & 15) as u8);
    match f {
        0 => Insn::Halt,
        1 => Insn::Nop,
        2 => Insn::JmpReg { b },
        3 => Insn::CallReg { b },
        4 => Insn::Ret,
        5 | 6 => {
            if !(1 <= a && a <= b && b <= 14) {
                return Insn::Illegal;
            }
            let cnt = b - a + 1;
            if f == 5 {
                Insn::Save { a, cnt }
            } else {
                Insn::Restore { a, cnt }
            }
        }
        7 => Insn::Rti,
        8 => Insn::SetI { val: 1 },
        9 => Insn::SetI { val: 0 },
        10 if b <= 1 => Insn::Mfsr { a, b },
        11 if a <= 1 => Insn::Mtsr { a, b },
        12 => Insn::Swi,
        13 if b != 15 => Insn::Set { a, cc: b },
        _ => Insn::Illegal,
    }
}

pub fn dec_unary(w: u32) -> Insn {
    let (d, s, f) = (((w >> 8) & 15) as u8, ((w >> 4) & 15) as u8, (w & 15) as u8);
    if f >= 12 {
        Insn::Illegal
    } else {
        Insn::Unary { d, s, f }
    }
}

pub fn dec_shift(w: u32) -> Insn {
    let (d, s, f) = (((w >> 8) & 15) as u8, ((w >> 4) & 15) as u8, (w & 15) as u8);
    let (op, t) = (f & 3, f >> 2);
    match t {
        3 => Insn::Illegal,
        2 => Insn::ShiftReg { d, s, op },
        _ => Insn::ShiftImm {
            d,
            op,
            cnt: s + 16 * t,
        },
    }
}

pub fn dec_bcc(pc: u32, w: u32) -> Insn {
    let cc = ((w >> 8) & 15) as u8;
    let nxt = pc.wrapping_add(2);
    let target = nxt.wrapping_add(sext8(w).wrapping_mul(2));
    if cc == 15 {
        Insn::Bsr { target }
    } else {
        Insn::Bcc { cc, target }
    }
}

/// Jcc, JMP and CALL with a 16-bit PC-relative or a 32-bit absolute
/// target; `parcel` reads the extension parcels.
pub fn dec_jcc(pc: u32, w: u32, parcel: &mut dyn FnMut(u32) -> Res<u32>) -> Res<Insn> {
    let (cc, k, z) = (((w >> 8) & 15) as u8, (w >> 4) & 15, w & 15);
    if k > 1 || z != 0 {
        return Ok(Insn::Illegal);
    }
    Ok(if k == 0 {
        let nxt = pc.wrapping_add(4);
        let target = nxt.wrapping_add(sext16(parcel(pc.wrapping_add(2))?).wrapping_mul(2));
        Insn::Jcc {
            cc,
            target,
            how: How::Rel,
        }
    } else {
        let target = (parcel(pc.wrapping_add(2))? | parcel(pc.wrapping_add(4))? << 16) & !1;
        Insn::Jcc {
            cc,
            target,
            how: How::Abs,
        }
    })
}
