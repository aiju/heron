//! The CPU: studies/mini/rtl.py's `RTL`, cycle for cycle. The comments
//! there say why; this follows its order, so the two can be read side by
//! side.

use crate::system::System;

/// A microword's fields, by their index in [`crate::FIELDS`].
pub type Word = [u32; crate::FIELDS.len()];

mod f {
    pub const NEXT: usize = 0;
    pub const SEQ: usize = 1;
    pub const COND: usize = 2;
    pub const ARF: usize = 3;
    pub const APC: usize = 4;
    pub const AR: usize = 5;
    pub const AR2: usize = 6;
    pub const PCK: usize = 7;
    pub const SINA: usize = 8;
    pub const BRF: usize = 9;
    pub const BR: usize = 10;
    pub const BL: usize = 11;
    pub const BX: usize = 12;
    pub const BS0: usize = 13;
    pub const BF1: usize = 14;
    pub const BF23: usize = 15;
    pub const RFA: usize = 16;
    pub const RFB: usize = 17;
    pub const RFW: usize = 18;
    pub const RFK: usize = 19;
    pub const RFKW: usize = 20;
    pub const RFWE: usize = 21;
    pub const LDSX: usize = 22;
    pub const LDEX: usize = 23;
    pub const S: usize = 24;
    pub const M: usize = 25;
    pub const CIN: usize = 26;
    pub const MQM: usize = 27;
    pub const MS: usize = 28;
    pub const RMS: usize = 29;
    pub const RZ: usize = 30;
    pub const SIN: usize = 31;
    pub const V8: usize = 32;
    pub const FSEL: usize = 33;
    pub const KONST: usize = 34;
    pub const LDSGN: usize = 35;
    pub const LDR: usize = 36;
    pub const LDMAR: usize = 37;
    pub const MARINC: usize = 38;
    pub const LDPC: usize = 39;
    pub const PCCOND: usize = 40;
    pub const CONSUME: usize = 41;
    pub const LDLC: usize = 42;
    pub const LCINC: usize = 43;
    pub const CCB: usize = 44;
    pub const MEM: usize = 45;
    pub const SIZE: usize = 46;
    pub const LDCL: usize = 47;
    pub const CLSRC: usize = 48;
    pub const LCL: usize = 49;
    pub const LL: usize = 50;
    pub const FNZ: usize = 51;
    pub const NSEL: usize = 52;
    pub const FC: usize = 53;
    pub const CZERO: usize = 54;
    pub const CSRC: usize = 55;
    pub const FV: usize = 56;
    pub const FI: usize = 57;
}

/// The control store: its distinct words and every address's (or none),
/// with the sequencer's fixed addresses and the length classes.
pub struct Rom {
    pub words: Vec<Word>,
    /// By microaddress (2^17 of them): an index into `words`, or -1.
    pub index: Vec<i32>,
    pub entry: u32,
    pub refill: u32,
    pub irq: u32,
    pub fault: [u32; 4],
    /// Ticks by length class (LCL).
    pub lengths: [u64; 4],
}

const SEQ_NEXT: u32 = 0;
const SEQ_DISPATCH: u32 = 2;
const SEQ_HALT: u32 = 3;
/// A parcel consumed with the queue empty comes from the word the cycle
/// fetches: the cycle is two ticks longer for it.
const DEMAND_HOLD: u64 = 2;

#[derive(Clone, Copy, PartialEq)]
enum Forced {
    None,
    Irq,
    Refill,
    Fault,
}

/// 74181 a nibble: F, and the carry out (true carries).
fn alu181(a: u32, b: u32, s: u32, m: u32, cin: u32) -> (u32, u32) {
    let (s0, s1, s2, s3) = (s & 1, (s >> 1) & 1, (s >> 2) & 1, (s >> 3) & 1);
    let (mut f, mut carry) = (0, cin);
    for i in 0..4 {
        let (ai, bi) = ((a >> i) & 1, (b >> i) & 1);
        let u = ai | (bi & s0) | ((bi ^ 1) & s1);
        let v = (ai & (bi ^ 1) & s2) | (ai & bi & s3);
        let h = u & (v ^ 1);
        let fi = if m != 0 { h ^ 1 } else { h ^ carry };
        f |= fi << i;
        carry = v | (u & carry);
    }
    (f, carry)
}

fn cond_true(n: u32, z: u32, c: u32, v: u32, cc: u32) -> u32 {
    let t = match cc >> 1 {
        0 => z,
        1 => c,
        2 => n,
        3 => v,
        4 => c & (z ^ 1),
        5 => u32::from(n == v),
        6 => (z ^ 1) & u32::from(n == v),
        _ => 1,
    };
    t ^ (cc & 1)
}

/// A bus lane: how many drivers, and the first one's value (None:
/// floating).
#[derive(Clone, Copy, Default)]
struct Lane {
    n: u8,
    v: Option<u32>,
}

impl Lane {
    fn put(&mut self, v: Option<u32>) {
        self.n += 1;
        if self.n == 1 {
            self.v = v;
        }
    }
}

pub struct Cpu {
    pub rom: Rom,
    alu: Vec<u8>,
    pub check: bool,
    pub depth: usize,
    pub jump_decodes: bool,
    pub rf: [u32; 32],
    pub r: u32,
    pub t: u32,
    pub tl: u32,
    pub mar: u32,
    pub pc: u32,
    pub fpc: u32,
    pub q0: u32,
    pub q1: u32,
    pub v0: u32,
    pub v1: u32,
    pub ir: u32,
    pub sx: u32,
    pub ex: u32,
    pub lc: u32,
    pub mq: u32,
    pub s33: u32,
    pub sgn: u32,
    pub cl: u32,
    pub n: u32,
    pub z: u32,
    pub c: u32,
    pub v: u32,
    pub i: u32,
    pub irqq: u32,
    pub pend: u32,
    pub uaddr: u32,
    uir: usize,
    pub cycles: u64,
    pub ticks: u64,
    pub hold_ticks: u64,
    pub steal_ticks: u64,
    pub instructions: u64,
    pub halted: bool,
    pub fetch_words: u64,
    pub fetch_wasted: u64,
    pub refills: u64,
    pub demand: u64,
    /// Executions by microaddress, if counted.
    pub ucount: Option<Vec<u64>>,
}

impl Cpu {
    pub fn new(
        rom: Rom,
        queue_words: usize,
        check: bool,
        jump_decodes: bool,
    ) -> Result<Cpu, String> {
        let first = *rom.index.first().ok_or("an empty control store")?;
        if first < 0 {
            return Err("the control store has no word at address 0".into());
        }
        let mut alu = vec![0u8; 32 * 512];
        for s in 0..16 {
            for m in 0..2 {
                for a in 0..16 {
                    for b in 0..16 {
                        for c in 0..2 {
                            let (fv, co) = alu181(a, b, s, m, c);
                            alu[((s * 2 + m) * 512 + ((a << 5) | (b << 1) | c)) as usize] =
                                (fv | (co << 4)) as u8;
                        }
                    }
                }
            }
        }
        Ok(Cpu {
            rom,
            alu,
            check,
            depth: queue_words,
            jump_decodes,
            rf: [0; 32],
            r: 0,
            t: 0,
            tl: 0,
            mar: 0,
            pc: 0,
            fpc: 0,
            q0: 0,
            q1: 0,
            v0: 0,
            v1: 0,
            ir: 0,
            sx: 0,
            ex: 0,
            lc: 0,
            mq: 0,
            s33: 0,
            sgn: 0,
            cl: 0,
            n: 0,
            z: 0,
            c: 0,
            v: 0,
            i: 0,
            irqq: 0,
            pend: 0,
            uaddr: 0,
            uir: first as usize,
            cycles: 0,
            ticks: 0,
            hold_ticks: 0,
            steal_ticks: 0,
            instructions: 0,
            halted: false,
            fetch_words: 0,
            fetch_wasted: 0,
            refills: 0,
            demand: 0,
            ucount: None,
        })
    }

    fn err<T>(&self, msg: &str) -> Result<T, String> {
        Err(format!(
            "cycle {} uaddr {:05X} PC {:08X}: {msg}",
            self.cycles, self.uaddr, self.pc
        ))
    }

    /// The plain machine's flags word: V C Z N I in bits 0-4.
    pub fn flags_word(&self) -> u32 {
        self.v | (self.c << 1) | (self.z << 2) | (self.n << 3) | (self.i << 4)
    }

    /// Register file address for a source (0 d, 1 r, 2 SX, 3 constant).
    fn rf_addr(&self, sel: u32, k: u32) -> usize {
        (match sel {
            0 => (self.ir >> 12) & 15,
            1 => (self.ir >> 8) & 15,
            2 => self.sx,
            _ => k,
        }) as usize
    }

    fn queue_len(&self) -> usize {
        if self.v0 == 0 {
            0
        } else if self.v1 == 0 {
            1
        } else {
            2
        }
    }

    fn alu32(&self, a: u32, b: u32, s: u32, m: u32, cin: u32) -> (u32, u32) {
        let base = ((s * 2 + m) * 512) as usize;
        let (mut f, mut c) = (0u32, cin);
        for k in 0..8 {
            let r = self.alu
                [base + ((((a >> (4 * k)) & 15) << 5) | (((b >> (4 * k)) & 15) << 1) | c) as usize];
            f |= u32::from(r & 15) << (4 * k);
            c = u32::from(r >> 4);
        }
        (f, c)
    }

    /// One clock cycle.
    pub fn step(&mut self, sysm: &mut System) -> Result<(), String> {
        let w: Word = self.rom.words[self.uir];
        let (ir, r, mar, pc) = (self.ir, self.r, self.mar, self.pc);
        let chk = self.check;
        let mut hold: u64 = 0;

        // ---- register file reads
        let rfk = w[f::RFK];
        let mut a: Option<u32> = None;
        let mut drv = 0;
        if w[f::ARF] != 0 {
            a = Some(self.rf[self.rf_addr(w[f::RFA], rfk)]);
            drv += 1;
        }
        if w[f::APC] != 0 {
            a = Some(pc | w[f::PCK]);
            drv += 1;
        }
        if w[f::AR] != 0 {
            a = Some(r);
            drv += 1;
        }
        if w[f::AR2] != 0 {
            let sina = match w[f::SINA] {
                0 => 0,
                1 => r >> 31,
                2 => self.c,
                _ => self.mq >> 31,
            };
            a = Some((r << 1) | sina);
            drv += 1;
        }
        if drv > 1 {
            return self.err("A bus contention");
        }

        // ---- the memory port: a data access, or a fetch
        let mem = w[f::MEM];
        let size = w[f::SIZE];
        let data_access = matches!(mem, 1 | 2 | 6);
        let reading = matches!(mem, 1 | 6);
        let mut va = mar;
        if mem == 6 {
            match a {
                None => return self.err("a read at the A bus with nothing on it"),
                Some(x) => va = x,
            }
        }
        let fault = data_access && size >= 2 && va & (if size == 2 { 1 } else { 3 }) != 0;
        let qlen = self.queue_len();
        let full = qlen >= self.depth;
        let mut fetched: Option<u32> = None;
        if (mem == 3 || !data_access) && !full {
            fetched = Some(sysm.fetch(self.fpc));
        }

        // ---- the queue as the decode sees it (with a fetch's word)
        let mut view = [0u32; 3];
        let mut vlen = 0;
        if qlen >= 1 {
            view[0] = self.q0;
            vlen = 1;
            if qlen >= 2 {
                view[1] = self.q1;
                vlen = 2;
            }
        }
        if let Some(x) = fetched {
            view[vlen] = x;
            vlen += 1;
        }
        let pc1 = (pc >> 1) & 1;
        let qh: Option<u32> = if vlen > 0 {
            Some(if pc1 != 0 {
                view[0] >> 16
            } else {
                view[0] & 0xFFFF
            })
        } else {
            None
        };

        // immediate unit
        let fill: Option<u32> = match w[f::FSEL] {
            0 => Some(0),
            1 => Some(1),
            3 => qh.map(|q| (q >> 15) & 1),
            4 => qh.map(|q| (q >> 7) & 1),
            5 => a.map(|x| (x >> 31) & 1),
            6 => a.map(|x| (x >> 15) & 1),
            7 => Some(self.sgn),
            _ => None,
        };
        let byte_of = |b: u32| if b != 0 { 0xFF } else { 0 };
        let v8: Option<u32> = match w[f::V8] {
            2 => fill.map(byte_of),
            3 => Some(self.lc),
            _ => Some(w[f::KONST]),
        };
        let fill8 = fill.map(byte_of);

        // B bus, by byte lane
        let mut lanes = [Lane::default(); 4];
        let put32 = |lanes: &mut [Lane; 4], x: u32| {
            for (k, lane) in lanes.iter_mut().enumerate() {
                lane.put(Some((x >> (8 * k)) & 0xFF));
            }
        };
        if w[f::BRF] != 0 {
            put32(&mut lanes, self.rf[self.rf_addr(w[f::RFB], rfk)]);
        }
        if w[f::BR] != 0 {
            put32(&mut lanes, r);
        }
        let bl = w[f::BL];
        // (the lanes from T: bl, T's lane, T or None while it's being read)
        let mut lanes_t: Option<(u32, u32, Option<u32>)> = None;
        if bl != 0 {
            if bl <= 3 {
                // T is transparent while memory is read into it this cycle
                lanes_t = Some(if reading {
                    (bl, va & 3, None)
                } else {
                    (bl, self.tl, Some(self.t))
                });
            } else {
                let q = match qh {
                    None => {
                        return self.err("the queue's head parcel used while the queue is empty");
                    }
                    Some(q) => q,
                };
                match bl {
                    4 => {
                        lanes[0].put(Some(q & 0xFF));
                        lanes[1].put(Some(q >> 8));
                    }
                    5 => {
                        let q2 = (q << 1) & 0xFFFF;
                        lanes[0].put(Some(q2 & 0xFF));
                        lanes[1].put(Some(q2 >> 8));
                    }
                    6 => {
                        lanes[2].put(Some(q & 0xFF));
                        lanes[3].put(Some(q >> 8));
                    }
                    _ => lanes[0].put(Some(q & 0xFF)),
                }
            }
        }
        if w[f::BS0] != 0 {
            lanes[0].put(v8);
        }
        if w[f::BF1] != 0 {
            lanes[1].put(fill8);
        }
        if w[f::BF23] != 0 {
            lanes[2].put(fill8);
            lanes[3].put(fill8);
        }
        match w[f::BX] {
            1 => put32(&mut lanes, self.mq),
            2 => lanes[0].put(Some(self.flags_word())),
            _ => {}
        }

        // ---- memory data, now that the address side is known
        let mut d: Option<u32> = None;
        if reading && fault {
            let (dv, h) = self.faulted(sysm, va);
            d = Some(dv);
            hold = h;
        } else if reading {
            let (dv, h) = sysm.read(va, size, self.cycles);
            d = Some(dv);
            hold += h;
        }
        if let Some((bl_, tl, tv)) = lanes_t {
            let tv = tv.unwrap_or(d.unwrap_or(0));
            match bl_ {
                1 => put32(&mut lanes, tv),
                2 => {
                    let h16 = if tl & 2 != 0 {
                        (tv >> 16) & 0xFFFF
                    } else {
                        tv & 0xFFFF
                    };
                    lanes[0].put(Some(h16 & 0xFF));
                    lanes[1].put(Some(h16 >> 8));
                }
                _ => lanes[0].put(Some((tv >> (8 * tl)) & 0xFF)),
            }
        }

        let mut b = 0u32;
        let mut bfull = true;
        for (k, lane) in lanes.iter().enumerate() {
            if lane.n > 1 {
                return self.err(&format!("B bus contention on byte {k}"));
            }
            if lane.n == 1 {
                match lane.v {
                    None => return self.err(&format!("B bus byte {k} from a floating source")),
                    Some(x) => b |= x << (8 * k),
                }
            } else {
                bfull = false;
            }
        }

        // ---- ALU
        let (mqm, ms) = (w[f::MQM], w[f::MS]);
        let cin = match w[f::CIN] {
            0 => 0,
            1 => 1,
            2 => self.c,
            3 => a.map_or(0, |x| x >> 31),
            4 => self.mq >> 31,
            5 => self.sgn,
            6 => self.mq & 1,
            _ => self.s33 ^ 1,
        };
        let mut gs = 0;
        let (s, m);
        if ms != 0 {
            let ga;
            if ms == 1 {
                ga = self.mq & 1;
            } else if ms == 2 {
                ga = 0;
                gs = self.mq & 1;
            } else if mqm == 2 {
                ga = self.s33;
                gs = self.s33 ^ 1;
            } else {
                ga = self.s33;
            }
            s = (ga << 3) | (gs << 2) | (gs << 1) | ga;
            m = w[f::M];
            if chk && (m != 0 || cin != gs) {
                return self.err("step with M set or the wrong carry in");
            }
        } else {
            s = w[f::S];
            m = w[f::M];
        }
        let uses_a = !(m == 1 && matches!(s, 0b1010 | 0b0011 | 0b1100 | 0b0101));
        let uses_b = !((m == 1 && matches!(s, 0b1111 | 0b0000 | 0b0011 | 0b1100))
            || (m == 0 && matches!(s, 0b0000 | 0b1111 | 0b1100)));
        let av = a.unwrap_or(0);
        let (fv, c32) = self.alu32(av, b, s, m, cin);
        let vt2 = ((av >> 31) ^ (b >> 31) ^ (s & 1)) & 1;
        let ovf = vt2 & ((av >> 31) ^ (fv >> 31)) & 1;
        let alu_ok = (a.is_some() || !uses_a) && (bfull || !uses_b);

        // result multiplexer
        let mut res = match w[f::RMS] {
            0 => fv,
            1 => {
                let mulstep = u32::from(mqm == 1);
                let sign = if vt2 != 0 {
                    (av >> 31) & 1
                } else {
                    (fv >> 31) & 1
                };
                let sin = [0, fv >> 31, self.c, fv & 1, c32, sign, 0, 0]
                    [(w[f::SIN] | (mulstep << 2)) as usize];
                (fv >> 1) | (sin << 31)
            }
            2 => fv.rotate_right(8),
            _ => fv.rotate_right(16),
        };
        let rz = w[f::RZ];
        for k in 0..4 {
            if (rz >> k) & 1 != 0 {
                res &= !(0xFF << (8 * k));
            }
        }
        let zero = u32::from(res == 0);

        // ---- stores: the A bus onto the memory data bus, by size
        if mem == 2 {
            let av_ = match a {
                None => return self.err("a store with nothing on the A bus"),
                Some(x) => x,
            };
            if fault {
                hold += self.faulted(sysm, mar).1;
            } else {
                hold += sysm.write(mar, size, av_, self.cycles);
            }
        }

        let extra = if w[f::CONSUME] != 0 && self.v0 == 0 {
            DEMAND_HOLD
        } else {
            0
        };
        // ---- sequencer
        let seq = w[f::SEQ];
        let mut jump = false;
        if w[f::LDPC] != 0 {
            jump = match w[f::PCCOND] {
                0 => true,
                1 => self.bcond(w[f::CCB]) != 0,
                _ => self.cl == 0,
            };
        }
        let mut forced = Forced::None;
        let mut decode_ok = false;
        let mut y;
        if seq == SEQ_NEXT {
            let cnd = w[f::COND];
            if cnd != 0 {
                if chk && w[f::NEXT] & 1 != 0 {
                    return self.err("branch with NEXT[0] set");
                }
                y = (w[f::NEXT] & !1) | self.ucond(cnd, &w)?;
            } else {
                y = w[f::NEXT];
            }
        } else if seq == SEQ_DISPATCH {
            let q = match qh {
                None => return self.err("dispatch with the queue empty"),
                Some(q) => q,
            };
            y = (w[f::NEXT] & !15) | ((q >> 8) & 15);
        } else if seq == SEQ_HALT {
            y = w[f::NEXT];
            if self.pend != 0 {
                forced = Forced::Irq;
                y = self.rom.irq;
            }
        } else if self.pend != 0 {
            forced = Forced::Irq;
            y = self.rom.irq;
        } else if vlen > 0
            && !jump
            && (qlen > 0 || mem == 3)
            && (self.jump_decodes || w[f::LDPC] == 0)
        {
            decode_ok = true;
            y = self.rom.entry + qh.unwrap_or(0);
        } else {
            forced = Forced::Refill;
            y = self.rom.refill;
        }

        let queue_decode = decode_ok;
        if fault {
            forced = Forced::Fault;
            y = self.rom.fault[(w[f::LL] & 3) as usize];
            decode_ok = false;
        }

        // ---- clock edge
        let i_now = self.i;
        if w[f::RFWE] != 0 && !fault {
            if chk && !alu_ok {
                return self.err("register write from a floating bus");
            }
            let k = self.rf_addr(w[f::RFW], w[f::RFKW]);
            self.rf[k] = res;
        }
        if w[f::LDR] != 0 {
            if chk && !alu_ok {
                return self.err("R loaded from a floating bus");
            }
            self.r = res;
        }
        if w[f::LDMAR] != 0 {
            if chk && !alu_ok {
                return self.err("MAR loaded from a floating bus");
            }
            self.mar = res;
        } else if w[f::MARINC] != 0 {
            self.mar = mar.wrapping_add(4);
        }
        if reading {
            self.t = d.unwrap_or(0);
            self.tl = va & 3;
        }
        if w[f::LDLC] != 0 {
            self.lc = res & 0xFF;
        } else if w[f::LCINC] != 0 {
            self.lc = (self.lc + 1) & 0xFF;
        }
        if mqm == 3 {
            if chk && !bfull {
                return self.err("MQ loaded from a floating bus");
            }
            self.mq = b;
            self.s33 = 0;
        } else if mqm == 1 {
            self.mq = ((fv & 1) << 31) | (self.mq >> 1);
        } else if mqm == 2 {
            let s33 = ((r >> 31) ^ c32 ^ gs) & 1;
            self.mq = (self.mq << 1) | (s33 ^ 1);
            self.s33 = s33;
        }
        if w[f::LDSGN] != 0 {
            match fill {
                None => return self.err("SGN loaded from a floating source"),
                Some(x) => self.sgn = x,
            }
        }
        if w[f::LDCL] != 0 {
            let cls = w[f::CLSRC];
            if cls == 0 {
                self.cl = zero;
            } else if cls == 1 {
                self.cl = c32;
            } else {
                let sh = if cls == 2 || cls == 4 { 16 } else { 15 };
                let hz = u32::from(res >> sh == 0);
                self.cl = if cls == 2 || cls == 3 {
                    hz
                } else {
                    self.cl & hz
                };
            }
        }
        match w[f::LDSX] {
            1 => self.sx = (ir >> 12) & 15,
            2 => self.sx = (self.sx + 1) & 15,
            3 => match qh {
                None => return self.err("SX loaded from an empty queue"),
                Some(q) => self.sx = (q >> 12) & 15,
            },
            _ => {}
        }
        match w[f::LDEX] {
            1 => self.ex = (ir >> 8) & 15,
            2 => match qh {
                None => return self.err("EX loaded from an empty queue"),
                Some(q) => self.ex = (q >> 12) & 15,
            },
            _ => {}
        }
        if !fault {
            self.flags(&w, res, fv, c32, ovf, zero, a, fill)?;
        }
        // the PC and the queue
        if jump {
            if chk && !alu_ok {
                return self.err("PC loaded from a floating bus");
            }
            if !fault {
                self.pc = res & 0xFFFF_FFFE;
            }
            self.fpc = res & 0xFFFF_FFFC;
            self.v0 = 0;
            self.v1 = 0;
            if fetched.is_some() {
                self.fetch_wasted += 1;
            }
        } else {
            let consume = w[f::CONSUME] != 0 || queue_decode;
            if w[f::CONSUME] != 0 && qlen == 0 {
                if fetched.is_none() {
                    return self.err("a parcel consumed from an empty queue, without a fetch");
                }
                self.demand += 1;
            }
            let mut first = 0;
            if fetched.is_some() {
                self.fpc = self.fpc.wrapping_add(4);
                self.fetch_words += 1;
            }
            if consume {
                if pc1 != 0 {
                    first = 1;
                }
                if !fault {
                    self.pc = pc.wrapping_add(2);
                }
            }
            let words = &view[first.min(vlen)..vlen];
            if words.len() > self.depth {
                return self.err("the queue overflowed");
            }
            self.v0 = u32::from(!words.is_empty());
            self.v1 = u32::from(words.len() > 1);
            if let Some(&x) = words.first() {
                self.q0 = x;
                if words.len() > 1 {
                    self.q1 = words[1];
                }
            }
        }
        if decode_ok {
            self.ir = qh.unwrap_or(0);
            self.instructions += 1;
        }
        if forced == Forced::Refill {
            self.refills += 1;
        }
        // the interrupt: the line sampled at every edge (IRQQ), the
        // decision (PEND) a cycle later from it and I as it is in this cycle
        self.pend = u32::from(self.irqq != 0 && i_now != 0);
        self.irqq = u32::from(sysm.irq());

        if seq == SEQ_HALT && forced == Forced::None && (self.i == 0 || !sysm.can_interrupt()) {
            self.halted = true;
        }
        let k = self.rom.lengths[(w[f::LCL] & 3) as usize] + extra + hold;
        let steal = sysm.cycle(k, hold);
        self.ticks += k + steal;
        self.hold_ticks += hold;
        self.steal_ticks += steal;
        self.cycles += 1;
        self.uaddr = y;
        if let Some(c) = self.ucount.as_mut() {
            c[y as usize] += 1;
        }
        let wi = self.rom.index.get(y as usize).copied().unwrap_or(-1);
        if wi < 0 {
            return self.err(&format!("jump to an empty control store word {y:05X}"));
        }
        self.uir = wi as usize;
        Ok(())
    }

    /// A misaligned access: what the data bus carries, and the hold.
    fn faulted(&self, sysm: &mut System, pa: u32) -> (u32, u64) {
        if !System::is_io(pa) {
            return (sysm.ram_word(pa), 0);
        }
        let hold = sysm.io_hold[((pa >> 28) & 7) as usize];
        sysm.io_ticks += hold;
        (0, hold)
    }

    #[allow(clippy::too_many_arguments)]
    fn flags(
        &mut self,
        w: &Word,
        res: u32,
        fv: u32,
        c32: u32,
        ovf: u32,
        zero: u32,
        a: Option<u32>,
        fill: Option<u32>,
    ) -> Result<(), String> {
        let fnz = w[f::FNZ];
        if fnz == 3 {
            // the flags word from the A bus: N Z C V, and I
            let a = match a {
                None => return self.err("flags loaded from a floating A bus"),
                Some(x) => x,
            };
            self.n = (a >> 3) & 1;
            self.z = (a >> 2) & 1;
            self.c = (a >> 1) & 1;
            self.v = a & 1;
            self.i = (a >> 4) & 1;
            return Ok(());
        }
        if fnz != 0 {
            let nbit = match w[f::NSEL] {
                0 => 31,
                1 => 15,
                2 => 7,
                _ => return self.err("unknown NSEL"),
            };
            let n = (res >> nbit) & 1;
            self.n = n;
            self.z = if fnz == 1 { zero } else { self.z & zero };
        }
        let fc = w[f::FC];
        if w[f::CZERO] != 0 {
            self.c = 0;
        } else if fc == 1 {
            let fl = fill.unwrap_or(0);
            self.c = match w[f::CSRC] {
                0 => (a.unwrap_or(0) >> 1) & 1,
                1 => fv & 1,
                2 => (fv >> 7) & 1,
                3 => (fv >> 8) & 1,
                4 => (fv >> 15) & 1,
                5 => fv >> 31,
                6 => ((fv >> 7) ^ fl) & 1,
                _ => ((fv >> 15) ^ fl) & 1,
            };
        } else if fc == 2 {
            self.c = c32;
        } else if fc == 3 {
            self.c = self.cl ^ 1;
        }
        match w[f::FV] {
            7 => self.v = ovf,
            2 => self.v = 0,
            4 => self.v = self.cl ^ 1,
            5 => self.v = 1,
            _ => {}
        }
        match w[f::FI] {
            1 => self.i = 1,
            2 => self.i = 0,
            _ => {}
        }
        Ok(())
    }

    /// A microcode branch condition.
    fn ucond(&self, cnd: u32, w: &Word) -> Result<u32, String> {
        Ok(match cnd {
            1 => u32::from(self.lc == 255),
            2 => self.r >> 31,
            3 => self.cl,
            4 | 7 => {
                let cc = self.cc_of(w[f::CCB]);
                if self.check && u32::from(cnd == 7) != (cc & 1) {
                    return self.err("condition polarity doesn't match the instruction");
                }
                cond_true(self.n, self.z, self.c, self.v, cc & 14) ^ u32::from(cnd == 7)
            }
            5 => self.mq >> 31,
            6 => u32::from(self.lc & 15 == 15),
            8 => self.pend,
            9 => u32::from(self.sx == self.ex),
            12 => u32::from(self.sx == 15),
            13 => self.mq & 1,
            14 => self.r & 1,
            _ => return self.err(&format!("unknown condition {cnd}")),
        })
    }

    fn cc_of(&self, ccb: u32) -> u32 {
        match ccb {
            0 => (self.ir >> 12) & 15,
            1 => self.ir & 15,
            _ => (self.ir >> 8) & 15,
        }
    }

    fn bcond(&self, ccb: u32) -> u32 {
        let cc = self.cc_of(ccb);
        if cc == 15 {
            0
        } else {
            cond_true(self.n, self.z, self.c, self.v, cc)
        }
    }
}
