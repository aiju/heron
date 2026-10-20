//! The two-halves machine, a microinstruction at a time: rtl2.py's model
//! in Rust, step for step, so that the two count the same cycles and,
//! with phase F's stretches off ([`crate::board::Config::stretch`]), the
//! same ticks.
//!
//! A cycle: phase F writes the cycle before's results to the register
//! file (the low half's, then the high half's); the low half, then the
//! high half if HLEN isn't 0, each read D, run the ALU on D and L, set the
//! flags and load L, PC and MAR as the word says; at the cycle's end the
//! sequencer picks the next word, and a task may start at a task point.

use crate::board::Board;
use crate::store::{
    Aop, Axm, Axp, Carry, Cond, Ds, Flop, Hx, Irn, Mop, Rm, Sel, Seq, Si, Store, Word,
};

/// The flags: U_FLG's (N Z C V I, IC and ST for the microcode) and
/// U_SYS's (the bank bits, INIT, IRQP).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Flags {
    pub n: bool,
    pub z: bool,
    pub c: bool,
    pub v: bool,
    pub i: bool,
    pub ic: bool,
    pub st: bool,
    pub b: bool,
    pub bi: bool,
    pub init: bool,
    pub irqp: bool,
}

/// Where a cycle went, for a profile.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner {
    /// The instruction at this address.
    Insn(u32),
    DeviceTask,
    Copper,
}

pub struct Cpu {
    /// The register file: [half << 7 | task << 6 | bank << 5 | n], n < 32
    /// (the bank only for n < 16).
    pub rf: [u16; 256],
    /// The operand latch's halves, and the result registers'.
    pub l: [u16; 2],
    pub y: [u16; 2],
    /// What D holds when nothing drives it.
    pub dhold: u16,
    /// The last cycle's result's write: its register (without the half),
    /// whether each half is written, and its HW.
    wa: usize,
    wenq: bool,
    wenbq: bool,
    hwq: u8,
    /// PC (bits 20-1), MAR (bits 20-0) and MAR's bit 30 (AIO).
    pub pc: u32,
    pub mar: u32,
    pub mar30: bool,
    /// The register byte.
    pub d: u8,
    pub s: u8,
    pub upc: u16,
    pub task: bool,
    pub tupc: u16,
    /// Which task runs: the device task's entry or the copper's.
    pub task_owner: Owner,
    pub f: Flags,
    /// The low half's carry out, for the high half.
    hc: bool,
    z_last: bool,
    bus_a: u32,
    fetch_pc: u32,
    /// TASK as the last phase F ended (U_LCK's TASKP, for TCHG).
    taskp: bool,
    /// The instruction the cycles are going to: the last fetch's address,
    /// from its decode on.
    pub insn_pc: u32,
    pub cycles: u64,
    pub ticks: u64,
    pub instructions: u64,
}

impl Default for Cpu {
    fn default() -> Cpu {
        Cpu::new()
    }
}

/// The 74F181s and the 74F182 as one 16-bit ALU: (F, carry out). Each
/// bit's u (A, B as S0 and S1 pick) and v (as S2 and S3 pick) have v <= u,
/// so in arithmetic mode F is u + v + carry.
#[inline]
fn alu181(a: u16, b: u16, op: &Aop, c: bool) -> (u16, bool) {
    let nb = !b;
    let u = a | (b & op.k[0]) | (nb & op.k[1]);
    let v = (a & nb & op.k[2]) | (a & b & op.k[3]);
    if op.m {
        return (!(u & !v), false);
    }
    let t = u as u32 + v as u32 + c as u32;
    (t as u16, t >> 16 != 0)
}

#[inline]
fn rmux(rm: Rm, f: u16, si: bool) -> u16 {
    match rm {
        Rm::Pass => f,
        Rm::Shr => f >> 1 | (si as u16) << 15,
        Rm::Zxb => f & 0xFF,
        Rm::Sxb => (f & 0xFF) | if f & 0x80 != 0 { 0xFF00 } else { 0 },
    }
}

impl Cpu {
    /// As reset leaves it: µPC 0 (the interrupt's entry, which goes to
    /// the reset routine while INIT is clear), no task, the flags clear.
    pub fn new() -> Cpu {
        Cpu {
            rf: [0; 256],
            l: [0; 2],
            y: [0; 2],
            dhold: 0,
            wa: 0,
            wenq: false,
            wenbq: false,
            hwq: 0,
            pc: 0,
            mar: 0,
            mar30: false,
            d: 0,
            s: 0,
            upc: 0,
            task: false,
            tupc: 0,
            task_owner: Owner::DeviceTask,
            f: Flags::default(),
            hc: false,
            z_last: false,
            bus_a: 0,
            fetch_pc: 0,
            taskp: false,
            insn_pc: 0,
            cycles: 0,
            ticks: 0,
            instructions: 0,
        }
    }

    /// The reset button (or power-on): the sequencer, the flags and the
    /// tasks' state cleared; the register file, L, PC and MAR as they were.
    pub fn reset(&mut self) {
        self.upc = 0;
        self.task = false;
        self.tupc = 0;
        self.f = Flags::default();
        self.wenq = false;
        self.wenbq = false;
    }

    /// The control store's address.
    #[inline]
    pub fn address(&self, st: &Store) -> usize {
        if self.task {
            (st.task_base | self.tupc) as usize
        } else {
            self.upc as usize
        }
    }

    /// A program register, as the program sees it in a bank.
    pub fn reg(&self, n: usize, bank: bool) -> u32 {
        let i = (bank as usize) << 5 | (n & 15);
        self.rf[i] as u32 | (self.rf[1 << 7 | i] as u32) << 16
    }

    pub fn set_reg(&mut self, n: usize, bank: bool, v: u32) {
        let i = (bank as usize) << 5 | (n & 15);
        self.rf[i] = v as u16;
        self.rf[1 << 7 | i] = (v >> 16) as u16;
    }

    /// The flags word: bit 0 V, 1 C, 2 Z, 3 N, 4 I, 5 B, 6 BI.
    pub fn flags_word(&self) -> u16 {
        let f = &self.f;
        f.v as u16
            | (f.c as u16) << 1
            | (f.z as u16) << 2
            | (f.n as u16) << 3
            | (f.i as u16) << 4
            | (f.b as u16) << 5
            | (f.bi as u16) << 6
    }

    /// A register select's place in the register file, but the half.
    #[inline]
    fn regsel(&self, sel: Sel, k: u8) -> usize {
        let n = match sel {
            Sel::K => k,
            Sel::D => self.d,
            Sel::S => self.s,
        } as usize;
        let bank = if n < 16 { self.f.b as usize } else { 0 };
        (self.task as usize) << 6 | bank << 5 | n
    }

    #[inline]
    fn cond(&self, c: Cond, b: &Board) -> bool {
        let f = &self.f;
        match c {
            Cond::True => true,
            Cond::Z => f.z,
            Cond::C => f.c,
            Cond::N => f.n,
            Cond::V => f.v,
            Cond::Hi => f.c && !f.z,
            Cond::Lt => f.n != f.v,
            Cond::Le => f.z || f.n != f.v,
            Cond::Ic => f.ic,
            Cond::St => f.st,
            Cond::Init => f.init,
            Cond::Irqp => f.irqp,
            Cond::Ne => self.d != self.s,
            Cond::A0 => false,
            Cond::Odt => b.odt_req(),
            Cond::I => f.i,
        }
    }

    /// Whether the jump at word `a` goes to `a` itself, with the flags and
    /// the board's lines as they are.
    pub fn jumps_to_itself(&self, w: &Word, a: usize, b: &Board) -> bool {
        w.seq == Seq::Jump && (w.jt ^ self.cond(w.cond, b) as u16) as usize == a
    }

    /// One microinstruction. `stretch`: phase F as the clock generator
    /// gives it (a tick more when a task starts or ends, two when the
    /// video's buffer is empty); without, always three ticks, as rtl2.py
    /// counts.
    #[inline]
    pub fn cycle(&mut self, st: &Store, b: &mut Board) -> Result<(), String> {
        let a = self.address(st);
        let w = &st.words[a];
        // phase F: the cycle before's results into the register file
        if self.wenq {
            self.rf[(self.hwq as usize) << 7 | self.wa] = self.y[0];
            self.dhold = self.y[0];
        }
        if self.wenbq {
            self.rf[((1 - self.hwq) as usize) << 7 | self.wa] = self.y[1];
            self.dhold = self.y[1];
        }
        let t0 = self.ticks;
        let mut fticks = 3;
        if b.cfg.stretch {
            fticks += (self.task != self.taskp) as u64 + b.video_phase_f(t0);
        }
        self.taskp = self.task;
        let mut t = t0 + fticks;
        let last = (w.hlen != 0) as usize;
        let mut ct = false;
        let mut md_last = None;
        for h in 0..=last {
            if h == last {
                // the condition: the flags as the last half starts
                ct = self.cond(w.cond, b);
            }
            let (md, n) = self.half(w, h, t, st, b)?;
            t += n;
            if md.is_some() {
                md_last = md;
            }
        }
        if w.cond == Cond::A0 {
            ct = self.bus_a & 1 != 0;
        }
        self.ticks = t;
        // ---- the cycle's end: the sequencer
        if w.fl.is_sys() {
            let z = self.z_last;
            match w.fl {
                Flop::Bnz => self.f.b = !z,
                Flop::Binz => self.f.bi = !z,
                Flop::Entry => self.f.b |= self.f.bi,
                _ => self.f.init = true,
            }
        }
        let irqp = (b.irq() && self.f.i) || b.odt_req();
        self.wenq = w.wen;
        self.wenbq = w.wen && last == 1;
        self.hwq = w.hw;
        self.wa = self.regsel(w.wsel, w.wk);
        let nib = if w.seq == Seq::Mw {
            match w.mw {
                0 => self.d,
                1 => self.s,
                _ => (md_last.unwrap_or(0) >> 8 & 15) as u8,
            }
        } else {
            0
        };
        let mut op = None;
        if matches!(w.mop, Mop::Fetch | Mop::Ldirm) && !self.task {
            let md = md_last.ok_or_else(|| format!("a decode without a read at {a:04X}"))?;
            self.d = (md >> 12) as u8;
            self.s = (md >> 8 & 15) as u8;
            op = Some(md & 0xFF);
            if w.mop == Mop::Fetch {
                self.instructions += 1;
            }
        } else if !self.task {
            match w.irn {
                Irn::None => {}
                Irn::IncD => self.d = (self.d + 1) & 15,
                Irn::DecS => self.s = self.s.wrapping_sub(1) & 15,
                Irn::Idx => {
                    let md = md_last.ok_or_else(|| format!("s <- x without a read at {a:04X}"))?;
                    self.s = (md >> 12) as u8;
                }
            }
        }
        // the next address
        let tp = matches!(w.seq, Seq::End | Seq::JumpT);
        let nxt = match w.seq {
            Seq::End => None,
            Seq::Mw => Some(w.jt | nib as u16),
            _ => Some(w.jt ^ ct as u16),
        };
        if self.task {
            match nxt {
                None => self.task = false,
                Some(n) => self.tupc = n & 0x7F,
            }
        } else {
            let n = match nxt {
                Some(n) => n,
                None => {
                    let op = op.ok_or_else(|| format!("a decode without a fetch at {a:04X}"))?;
                    if w.mop == Mop::Fetch {
                        self.insn_pc = self.fetch_pc;
                    }
                    let chk = w.jt & st.nochk == 0;
                    if chk && self.f.irqp {
                        op
                    } else {
                        st.entry_base | op
                    }
                }
            };
            self.upc = n & 0x1FFF;
            if tp {
                let dreq = b.dreq();
                if dreq || b.copreq() {
                    // the device task first
                    self.task = true;
                    let (base, owner) = if dreq {
                        (st.device_base, Owner::DeviceTask)
                    } else {
                        (st.copper_base, Owner::Copper)
                    };
                    self.tupc = base & 0x7F;
                    self.task_owner = owner;
                }
            }
        }
        self.f.irqp = irqp;
        self.cycles += 1;
        Ok(())
    }

    /// One half: the memory's data if it read, and its ticks. `t` is the
    /// tick it starts at.
    #[inline(always)]
    fn half(
        &mut self,
        w: &Word,
        h: usize,
        t: u64,
        st: &Store,
        b: &mut Board,
    ) -> Result<(Option<u16>, u64), String> {
        let p = &w.halves[h];
        let a = if p.at_pc { self.pc } else { self.mar };
        self.bus_a = a;
        let io = !p.at_pc && self.mar30;
        if p.mop == Mop::Fetch {
            self.fetch_pc = self.pc;
        }
        let md = if p.reads {
            Some(b.read16(a, io, t, self.cycles))
        } else {
            None
        };
        let f = self.f;
        let d = match p.ds {
            Ds::Rf => self.rf[(p.hr as usize) << 7 | self.regsel(w.rsel, w.rk)],
            Ds::Mem => {
                let md = md.ok_or_else(|| {
                    format!("D from memory without a read at {:04X}", self.address(st))
                })?;
                if w.sz {
                    (if a & 1 != 0 { md >> 8 } else { md }) & 0xFF
                } else {
                    md
                }
            }
            Ds::Imm => st.imm(w.imm, self.d, self.s, h == 1, f.st),
            Ds::Adr => {
                if h == 1 {
                    (self.pc >> 16 & 0x1F) as u16
                } else {
                    a as u16
                }
            }
            Ds::Pch => (self.pc >> 16 & 0x1F) as u16,
            Ds::Flw => self.flags_word(),
            Ds::None => self.dhold,
        };
        self.dhold = d;
        // the ALU
        let op = st.aops[w.aop as usize][f.st as usize];
        let cin = if h == 1 {
            self.hc
        } else {
            match op.carry {
                Carry::Zero => false,
                Carry::One => true,
                Carry::C => f.c,
                Carry::Ic => f.ic,
            }
        };
        let lh = self.l[h];
        let (fv, co) = alu181(d, lh, &op, cin);
        let r = match w.rm {
            Rm::Pass => fv,
            rm => {
                let si = match w.si {
                    Si::Zero => false,
                    Si::C => f.c,
                    Si::D15 => d >> 15 != 0,
                    Si::Co => co,
                };
                rmux(rm, fv, si)
            }
        };
        let res = match p.hx {
            Hx::Zero => 0,
            Hx::Fill => {
                if f.st {
                    0xFFFF
                } else {
                    0
                }
            }
            _ => r,
        };
        let mut n = p.ticks as u64;
        match p.mop {
            Mop::Wrm => {
                if w.sz {
                    b.write(a, (d & 0xFF) * 0x101, if a & 1 != 0 { 2 } else { 1 }, io, t);
                } else if a & 1 == 0 {
                    b.write(a, d, 3, io, t);
                }
                if io {
                    n = b.io_ticks(a);
                }
            }
            Mop::Rdm | Mop::Ldirm if io => {
                b.read_edge(a, self.cycles);
                n = b.io_ticks(a);
            }
            _ => {}
        }
        // ---- the half's end
        if p.flop != Flop::None {
            self.flags(p.flop, r, fv, co, d, lh);
        }
        self.z_last = r == 0;
        if h == 0 {
            self.hc = co;
        }
        if w.ldl {
            self.l[h] = d;
        }
        self.y[h] = res;
        // PC and MAR from the ALU
        let fw = fv as u32;
        match p.axp {
            Axp::Lo => self.pc = (self.pc & 0x1F_0000) | (fw & 0xFFFE),
            Axp::Hi => self.pc = (self.pc & 0xFFFF) | (fw & 0x1F) << 16,
            Axp::None => {
                if p.pc_inc {
                    self.pc = (self.pc + 2) & 0x1F_FFFF;
                }
            }
        }
        match p.axm {
            Axm::Lo => self.mar = (self.mar & 0x1F_0000) | fw,
            Axm::Hi => {
                self.mar = (self.mar & 0xFFFF) | (fw & 0x1F) << 16;
                self.mar30 = fw >> 14 & 1 != 0;
            }
            Axm::Inc => self.mar = (self.mar & 1) | ((self.mar & 0x1F_FFFE) + 2) & 0x1F_FFFE,
            Axm::None => {}
        }
        Ok((md, n))
    }

    #[inline]
    fn flags(&mut self, op: Flop, r: u16, fv: u16, co: bool, d: u16, l: u16) {
        let f = &mut self.f;
        let z = r == 0;
        let n15 = r >> 15 != 0;
        let (f0, f1) = (fv & 1 != 0, fv & 2 != 0);
        let (a15, b15) = (d >> 15 != 0, l >> 15 != 0);
        let v = |sub: bool| {
            if sub {
                a15 != b15 && n15 != a15
            } else {
                a15 == b15 && n15 != a15
            }
        };
        match op {
            Flop::None | Flop::Bnz | Flop::Binz | Flop::SetInit => {}
            // U_FLG's part; B is U_SYS's, at the cycle's end
            Flop::Entry => f.i = false,
            Flop::AddLo | Flop::SubLo => (f.c, f.z) = (co, z),
            Flop::AdcLo | Flop::SbcLo => (f.c, f.z) = (co, f.z && z),
            Flop::AddHi => (f.c, f.z, f.n, f.v) = (co, f.z && z, n15, v(false)),
            Flop::SubHi => (f.c, f.z, f.n, f.v) = (co, f.z && z, n15, v(true)),
            Flop::IcLo => f.ic = co,
            Flop::IcLoZ => (f.ic, f.z) = (co, z),
            Flop::IcStz => (f.ic, f.st) = (co, z),
            Flop::LogLo => f.z = z,
            Flop::LogHi => (f.z, f.n) = (f.z && z, n15),
            Flop::Nz16 => (f.n, f.z) = (n15, z),
            Flop::Shr => (f.c, f.v) = (f0, false),
            Flop::Shl => (f.c, f.v) = (co, false),
            Flop::Stn => f.st = n15,
            Flop::Stz => f.st = z,
            Flop::Stz32 => f.st = f.st && z,
            Flop::Stf0 => f.st = f0,
            Flop::Sta4 => f.st = f0 || f1,
            Flop::Stc => f.st = f.c,
            Flop::Cnz => f.c = !z,
            Flop::Vnz => f.v = !z,
            Flop::Znz => f.z = !z,
            Flop::Nnz => f.n = !z,
            Flop::Inz => f.i = !z,
            Flop::SetI => f.i = true,
            Flop::ClrI => f.i = false,
        }
    }
}
