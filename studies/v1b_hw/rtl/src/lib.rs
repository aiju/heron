//! The draft 1b hardware's register-transfer model: studies/v1b_hw/rtl.py
//! in Rust. It runs the microcode ROM images that ucode.py generates, one
//! clock cycle at a time, on a functional model of the datapath (buses,
//! registers, the 74181 ALU, the result multiplexer, flags, sequencer), and
//! checks the microcode's rules as it goes, as the Python model does.
//!
//! [`Rtl`] is the processor. It reaches memory and devices through a
//! [`Bus`]: [`Ram`] is the whole machine of rtl.py (1 MB and the console
//! and timer of the I/O page), and [`shadow::Shadow`] follows the
//! instruction-level simulator and times each instruction it executes.

use std::sync::{Arc, OnceLock};

pub mod shadow;

pub const Y_BITS: u32 = 12;
/// ROM address bits above Y: IRQP, then FAULT, then FAULT & LEN.
pub const IRQP_BIT: u32 = Y_BITS;
pub const FAULT_BIT: u32 = Y_BITS + 1;
/// Words in the microcode ROMs as the sequencer addresses them.
pub const ROM_WORDS: usize = 1 << (FAULT_BIT + 3);
/// Words in the decode ROM: {GOIRQ, parcel}.
pub const DECODE_WORDS: usize = 1 << 17;
pub const RAM_SIZE: u32 = 0x10_0000;
/// The register file's HI location (ucode.HI).
pub const HI: usize = 16;

/// ROM address of the address error entry for instruction length `ln`.
pub fn fault_page(ln: u32) -> u32 {
    (1 << FAULT_BIT) | (ln << (FAULT_BIT + 1))
}

/// A microinstruction: the control word's fields as logical values
/// (active-low fields already inverted), as ucode.unpack gives them.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Ctl {
    pub next: u16,
    pub seq: u8,
    pub cond: u8,
    pub goirq: u8,
    pub halt: u8,
    pub arf: u8,
    pub apc: u8,
    pub ar: u8,
    pub ar2: u8,
    pub abr: u8,
    pub brf: u8,
    pub br: u8,
    pub bt0: u8,
    pub bt1: u8,
    pub bt23: u8,
    pub bs0: u8,
    pub bf1: u8,
    pub bf23: u8,
    pub bmq: u8,
    pub bfl: u8,
    pub bt2: u8,
    pub tlane: u8,
    pub dsrc: u8,
    pub rfa: u8,
    pub rfb: u8,
    pub ldx: u8,
    pub rfk: u8,
    pub rfwe: u8,
    pub wr0: u8,
    pub s: u8,
    pub m: u8,
    pub cin: u8,
    pub mqm: u8,
    pub ms: u8,
    pub rms: u8,
    pub rz: u8,
    pub sin: u8,
    pub sina: u8,
    pub v8: u8,
    pub fsel: u8,
    pub konst: u8,
    pub ldsgn: u8,
    pub ldr: u8,
    pub ldmar: u8,
    pub marsrc: u8,
    pub ldtl: u8,
    pub ldth: u8,
    pub ldir: u8,
    pub ldpc: u8,
    pub pccond: u8,
    pub ldlc: u8,
    pub lcinc: u8,
    pub ccb: u8,
    pub memrd: u8,
    pub memwr: u8,
    pub addrmar: u8,
    pub size: u8,
    pub hiword: u8,
    pub fnz: u8,
    pub fc: u8,
    pub czero: u8,
    pub csrc: u8,
    pub fv: u8,
    pub fi: u8,
    pub ldcl: u8,
    pub clsrc: u8,
}

impl Ctl {
    /// Set a field by its name in ucode.FIELDS.
    pub fn set(&mut self, name: &str, v: u32) -> Result<(), String> {
        let b = v as u8;
        match name {
            "NEXT" => self.next = v as u16,
            "SEQ" => self.seq = b,
            "COND" => self.cond = b,
            "GOIRQ" => self.goirq = b,
            "HALT" => self.halt = b,
            "ARF" => self.arf = b,
            "APC" => self.apc = b,
            "AR" => self.ar = b,
            "AR2" => self.ar2 = b,
            "ABR" => self.abr = b,
            "BRF" => self.brf = b,
            "BR" => self.br = b,
            "BT0" => self.bt0 = b,
            "BT1" => self.bt1 = b,
            "BT23" => self.bt23 = b,
            "BS0" => self.bs0 = b,
            "BF1" => self.bf1 = b,
            "BF23" => self.bf23 = b,
            "BMQ" => self.bmq = b,
            "BFL" => self.bfl = b,
            "BT2" => self.bt2 = b,
            "TLANE" => self.tlane = b,
            "DSRC" => self.dsrc = b,
            "RFA" => self.rfa = b,
            "RFB" => self.rfb = b,
            "LDX" => self.ldx = b,
            "RFK" => self.rfk = b,
            "RFWE" => self.rfwe = b,
            "WR0" => self.wr0 = b,
            "S" => self.s = b,
            "M" => self.m = b,
            "CIN" => self.cin = b,
            "MQM" => self.mqm = b,
            "MS" => self.ms = b,
            "RMS" => self.rms = b,
            "RZ" => self.rz = b,
            "SIN" => self.sin = b,
            "SINA" => self.sina = b,
            "V8" => self.v8 = b,
            "FSEL" => self.fsel = b,
            "KONST" => self.konst = b,
            "LDSGN" => self.ldsgn = b,
            "LDR" => self.ldr = b,
            "LDMAR" => self.ldmar = b,
            "MARSRC" => self.marsrc = b,
            "LDTL" => self.ldtl = b,
            "LDTH" => self.ldth = b,
            "LDIR" => self.ldir = b,
            "LDPC" => self.ldpc = b,
            "PCCOND" => self.pccond = b,
            "LDLC" => self.ldlc = b,
            "LCINC" => self.lcinc = b,
            "CCB" => self.ccb = b,
            "MEMRD" => self.memrd = b,
            "MEMWR" => self.memwr = b,
            "ADDRMAR" => self.addrmar = b,
            "SIZE" => self.size = b,
            "HIWORD" => self.hiword = b,
            "FNZ" => self.fnz = b,
            "FC" => self.fc = b,
            "CZERO" => self.czero = b,
            "CSRC" => self.csrc = b,
            "FV" => self.fv = b,
            "FI" => self.fi = b,
            "LDCL" => self.ldcl = b,
            "CLSRC" => self.clsrc = b,
            _ => return Err(format!("unknown control field {name:?}")),
        }
        Ok(())
    }
}

/// The microcode: every ROM address's microinstruction, the decode ROM,
/// and what the tools need to know about the routines.
pub struct Rom {
    pub words: Vec<Ctl>,
    /// {GOIRQ, parcel} -> Y | LEN << Y_BITS
    pub decode: Vec<u32>,
    /// By first parcel: the decode ROM picks the illegal-instruction
    /// routine (the instructions the hardware doesn't implement).
    pub illegal: Vec<bool>,
    /// The interrupt entry routine's address.
    pub irq_entry: u32,
}

impl Rom {
    /// A ROM from ucode.py's tables: the field names, the distinct
    /// microinstructions as rows of field values, the row at each ROM
    /// address, and the decode ROM.
    pub fn new(
        names: &[String],
        rows: &[Vec<u32>],
        index: &[u32],
        decode: Vec<u32>,
        illegal: Vec<bool>,
        irq_entry: u32,
    ) -> Result<Rom, String> {
        if index.len() != ROM_WORDS || decode.len() != DECODE_WORDS || illegal.len() != 0x10000 {
            return Err("wrong ROM sizes".into());
        }
        let mut ctls = Vec::with_capacity(rows.len());
        for row in rows {
            if row.len() != names.len() {
                return Err("a microinstruction with the wrong number of fields".into());
            }
            let mut c = Ctl::default();
            for (n, &v) in names.iter().zip(row) {
                c.set(n, v)?;
            }
            ctls.push(c);
        }
        let words = index
            .iter()
            .map(|&i| ctls.get(i as usize).copied().ok_or("bad ROM index"))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Rom {
            words,
            decode,
            illegal,
            irq_entry,
        })
    }
}

/// The 74181 array, a nibble at a time: [(S, M)][a << 5 | b << 1 | cin] =
/// F | carry out << 4.
fn alu_table() -> &'static [u8] {
    static TABLE: OnceLock<Vec<u8>> = OnceLock::new();
    TABLE.get_or_init(|| {
        let mut t = vec![0u8; 32 * 512];
        for s in 0..16u32 {
            for m in 0..2u32 {
                for a in 0..16u32 {
                    for b in 0..16u32 {
                        for cin in 0..2u32 {
                            let (f, c) = alu181(a, b, s, m, cin);
                            t[((s * 2 + m) * 512 + (a << 5 | b << 1 | cin)) as usize] =
                                (f | c << 4) as u8;
                        }
                    }
                }
            }
        }
        t
    })
}

/// One 74181 (active-high data, true carries): (F, carry out).
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

/// The 32-bit 74181 array: (F, carry out).
pub fn alu32(a: u32, b: u32, s: u32, m: u32, cin: u32) -> (u32, u32) {
    let t = &alu_table()[((s * 2 + m) * 512) as usize..][..512];
    let (mut f, mut c) = (0, cin);
    for k in 0..8 {
        let r = t[((((a >> (4 * k)) & 15) << 5) | (((b >> (4 * k)) & 15) << 1) | c) as usize];
        f |= ((r & 15) as u32) << (4 * k);
        c = (r >> 4) as u32;
    }
    (f, c)
}

/// What the processor sees outside itself: memory, the I/O page and the
/// timer's interrupt request.
pub trait Bus {
    /// A 16-bit read: of RAM at `addr`, or of the I/O page when `io`
    /// (`fault`: the access is misaligned and blocked; `fetch`: it is at
    /// the PC, an opcode or extension parcel).
    fn read(&mut self, addr: u32, io: bool, fault: bool, fetch: bool, cycle: u64) -> u32;
    /// A 16-bit write; `lanes` bit 0 is the low byte, bit 1 the high one.
    fn write(&mut self, addr: u32, io: bool, d: u32, lanes: u32);
    /// The timer's interrupt request.
    fn irq(&self) -> u32;
    /// One clock cycle passes.
    fn tick(&mut self);
    /// The timer is running (HALT waits for it).
    fn timer_on(&self) -> bool;
}

/// The I/O page seen from a 16-bit bus (rtl.py's IODev): registers are 32
/// bits, read and written a half at a time.
#[derive(Default)]
pub struct IoDev {
    pub inp: Vec<u8>,
    pub pos: usize,
    pub out: Vec<u8>,
    pub period: u32,
    pub count: u32,
    pub flag: u32,
    last_empty: bool,
    cyc_hi: u32,
}

impl IoDev {
    pub fn read(&mut self, off: u32, cycle: u64) -> u32 {
        match off & 0xFE {
            0x00 => {
                if let Some(&b) = self.inp.get(self.pos) {
                    self.pos += 1;
                    self.last_empty = false;
                    b as u32
                } else {
                    self.last_empty = true;
                    0xFFFF
                }
            }
            0x02 => {
                if self.last_empty {
                    0xFFFF
                } else {
                    0
                }
            }
            0x04 => {
                if self.pos < self.inp.len() {
                    1
                } else {
                    2
                }
            }
            0x08 => self.period & 0xFFFF,
            0x0A => self.period >> 16,
            0x0C => self.flag,
            0x10 => {
                self.cyc_hi = ((cycle >> 16) & 0xFFFF) as u32;
                (cycle & 0xFFFF) as u32
            }
            0x12 => self.cyc_hi,
            _ => 0,
        }
    }

    pub fn write(&mut self, off: u32, v: u32, lanes: u32) {
        match off & 0xFE {
            0x00 if lanes & 1 != 0 => self.out.push(v as u8),
            0x08 => {
                self.period = v;
                self.count = 0;
                if v == 0 {
                    self.flag = 0;
                }
            }
            0x0A => {
                self.period = (self.period & 0xFFFF) | v << 16;
                self.count = 0;
                if self.period == 0 {
                    self.flag = 0;
                }
            }
            0x0C | 0x0E => self.flag = 0,
            _ => {}
        }
    }

    pub fn tick(&mut self) {
        if self.period != 0 {
            self.count += 1;
            if self.count >= self.period {
                self.flag = 1;
                self.count = 0;
            }
        }
    }
}

/// The whole machine's memory: 1 MB of RAM and the I/O page.
pub struct Ram {
    pub mem: Vec<u8>,
    pub dev: IoDev,
}

impl Ram {
    pub fn new(image: &[u8], inp: &[u8]) -> Ram {
        let mut mem = vec![0u8; RAM_SIZE as usize];
        let n = image.len().min(mem.len());
        mem[..n].copy_from_slice(&image[..n]);
        Ram {
            mem,
            dev: IoDev {
                inp: inp.to_vec(),
                ..IoDev::default()
            },
        }
    }
}

impl Bus for Ram {
    fn read(&mut self, addr: u32, io: bool, fault: bool, _fetch: bool, cycle: u64) -> u32 {
        if io {
            if fault {
                return 0;
            }
            return self.dev.read(addr & 0xFF, cycle) & 0xFFFF;
        }
        let a = (addr & 0xFFFFE) as usize;
        self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8
    }

    fn write(&mut self, addr: u32, io: bool, d: u32, lanes: u32) {
        if io {
            self.dev.write(addr & 0xFF, d, lanes);
            return;
        }
        let a = (addr & 0xFFFFE) as usize;
        if lanes & 1 != 0 {
            self.mem[a] = d as u8;
        }
        if lanes & 2 != 0 {
            self.mem[a + 1] = (d >> 8) as u8;
        }
    }

    fn irq(&self) -> u32 {
        self.dev.flag
    }

    fn tick(&mut self) {
        self.dev.tick();
    }

    fn timer_on(&self) -> bool {
        self.dev.period != 0
    }
}

/// The processor: the register file (r0-r15, HI at 16, scratch and the
/// loop constants above), the datapath registers, the flags and the
/// sequencer.
pub struct Rtl {
    pub rom: Arc<Rom>,
    /// Check the microcode's rules (floating buses used, conditions).
    pub check: bool,
    pub rf: [u32; 32],
    pub r: u32,
    pub t: u32,
    pub mar: u32,
    pub pc: u32,
    pub ir: u32,
    pub len: u32,
    pub lc: u32,
    pub mq: u32,
    pub sx: u32,
    pub s33: u32,
    pub sgn: u32,
    pub cl: u32,
    pub n: u32,
    pub z: u32,
    pub c: u32,
    pub v: u32,
    pub i: u32,
    pub irqs: u32,
    pub irqp: u32,
    /// The address of the microinstruction the next cycle executes.
    pub uaddr: u32,
    /// Cycles since the reset routine's fetch.
    pub cycles: u64,
    pub total: u64,
    pub started: bool,
    pub halted: bool,
    /// The last cycle fetched an opcode: (address, parcel).
    pub fetched: Option<(u32, u32)>,
    /// The last cycle ended an instruction (a decode, fetching or not).
    pub ended: bool,
    /// The last cycle's microinstruction had HALT set.
    pub at_halt: bool,
}

impl Rtl {
    pub fn new(rom: Arc<Rom>) -> Rtl {
        Rtl {
            rom,
            check: true,
            rf: [0; 32],
            r: 0,
            t: 0,
            mar: 0,
            pc: 0,
            ir: 0,
            len: 0,
            lc: 0,
            mq: 0,
            sx: 0,
            s33: 0,
            sgn: 0,
            cl: 0,
            n: 0,
            z: 0,
            c: 0,
            v: 0,
            i: 0,
            irqs: 0,
            irqp: 0,
            uaddr: 0,
            cycles: 0,
            total: 0,
            started: false,
            halted: false,
            fetched: None,
            ended: false,
            at_halt: false,
        }
    }

    fn err<T>(&self, msg: &str) -> Result<T, String> {
        Err(format!(
            "cycle {} uaddr {:04X}: {msg}",
            self.cycles, self.uaddr
        ))
    }

    pub fn flags_byte(&self) -> u32 {
        self.v | self.c << 1 | self.z << 2 | self.n << 3 | self.i << 4
    }

    pub fn bcond(&self, cc: u32) -> u32 {
        if cc == 15 {
            return 0;
        }
        let t = match cc >> 1 {
            0 => self.z,
            1 => self.c,
            2 => self.n,
            3 => self.v,
            4 => self.c & (self.z ^ 1),
            5 => (self.n == self.v) as u32,
            6 => (self.z ^ 1) & (self.n == self.v) as u32,
            _ => 1,
        };
        t ^ (cc & 1)
    }

    /// One clock cycle.
    pub fn step<B: Bus>(&mut self, bus: &mut B) -> Result<(), String> {
        let f = self.rom.words[self.uaddr as usize];
        let (ir, t, r, mar, pc) = (self.ir, self.t, self.r, self.mar, self.pc);
        let chk = self.check;
        self.fetched = None;
        self.ended = false;
        self.at_halt = f.halt != 0;

        // register file addresses
        let rfk = f.rfk as u32;
        let srcs = [(ir >> 8) & 15, ir & 15, self.sx, rfk & 15];
        let rfa = (srcs[f.rfa as usize] | if f.rfa == 3 { rfk & 16 } else { 0 }) as usize;
        let rfb = (srcs[f.rfb as usize] | if f.rfb == 3 { rfk & 16 } else { 0 }) as usize;

        // A bus (unless bridged from B), then B bus
        let bridge = f.abr != 0;
        let mut a: Option<u32> = None;
        if !bridge {
            let mut drivers = 0;
            if f.arf != 0 {
                a = Some(self.rf[rfa]);
                drivers += 1;
            }
            if f.apc != 0 {
                a = a.or(Some(pc));
                drivers += 1;
            }
            if f.ar != 0 {
                a = a.or(Some(r));
                drivers += 1;
            }
            if f.ar2 != 0 {
                let sina = [0, r >> 31, self.c, self.mq >> 31][f.sina as usize];
                a = a.or(Some((r << 1) | sina));
                drivers += 1;
            }
            if drivers > 1 {
                return self.err("A bus contention");
            }
        }
        let fsel = f.fsel;
        let mut fill: Option<u32> = if (fsel == 5 || fsel == 6) && a.is_none() {
            None
        } else {
            let av = a.unwrap_or(0);
            Some(match fsel {
                0 => 0,
                1 => 1,
                2 => (ir >> 7) & 1,
                3 => (t >> 7) & 1,
                4 => (t >> 15) & 1,
                5 => (av >> 31) & 1,
                6 => (av >> 15) & 1,
                _ => self.sgn,
            })
        };
        let fill_set = fill.unwrap_or(0) != 0;
        let v8 = match f.v8 {
            0 => (ir << 1) & 0xFE,
            1 => f.konst as u32,
            2 => {
                if fill_set {
                    0xFF
                } else {
                    0
                }
            }
            _ => self.lc,
        };
        let fill8 = if fill_set { 0xFF } else { 0 };
        let mut cnt = [0u8; 4];
        let mut val = [0u32; 4];
        let mut drive = |k: usize, v: u32| {
            cnt[k] += 1;
            val[k] = v & 0xFF;
        };
        if f.brf != 0 {
            let x = self.rf[rfb];
            for k in 0..4 {
                drive(k, x >> (8 * k));
            }
        }
        if f.br != 0 {
            for k in 0..4 {
                drive(k, r >> (8 * k));
            }
        }
        if f.bmq != 0 {
            for k in 0..4 {
                drive(k, self.mq >> (8 * k));
            }
        }
        if f.bt0 != 0 {
            drive(
                0,
                if f.tlane != 0 && mar & 1 != 0 {
                    t >> 8
                } else {
                    t
                },
            );
        }
        if f.bt1 != 0 {
            drive(1, t >> 8);
        }
        if f.bt23 != 0 {
            drive(2, t >> 16);
            drive(3, t >> 24);
        }
        if f.bt2 != 0 {
            let t2 = (t << 1) & 0xFFFF;
            drive(0, t2);
            drive(1, t2 >> 8);
        }
        if f.bs0 != 0 {
            drive(0, v8);
        }
        if f.bfl != 0 {
            drive(0, self.flags_byte());
        }
        if f.bf1 != 0 {
            drive(1, fill8);
        }
        if f.bf23 != 0 {
            drive(2, fill8);
            drive(3, fill8);
        }
        let mut b = 0u32;
        let mut bfull = true;
        let fill_used = f.bf1 != 0 || f.bf23 != 0 || f.v8 == 2;
        for k in 0..4 {
            if cnt[k] > 1 {
                return self.err(&format!("B bus contention on byte {k}"));
            }
            if cnt[k] == 1 {
                if fill.is_none() && fill_used {
                    return self.err("fill from a floating A bus");
                }
                b |= val[k] << (8 * k);
            } else {
                bfull = false;
            }
        }
        if bridge {
            if f.arf != 0 || f.apc != 0 || f.ar != 0 || f.ar2 != 0 {
                return self.err("A bus contention with the bridge");
            }
            if (fsel == 5 || fsel == 6) && fill_used {
                return self.err("fill from the A bus while bridged");
            }
            a = if bfull { Some(b) } else { None };
            if fsel == 5 || fsel == 6 {
                let Some(av) = a else {
                    return self.err("fill from a floating bridge");
                };
                fill = Some((av >> if fsel == 5 { 31 } else { 15 }) & 1);
            }
        }

        // ALU
        let (mqm, ms) = (f.mqm, f.ms);
        let av = a.unwrap_or(0);
        let cin = match f.cin {
            0 => 0,
            1 => 1,
            2 => self.c,
            3 => av >> 31,
            4 => self.mq >> 31,
            5 => self.sgn,
            6 => self.mq & 1,
            _ => self.s33 ^ 1,
        };
        let mut gs = 0;
        let (s, m) = if ms != 0 {
            let (ga, g) = match ms {
                // add X if the multiplier bit is 1
                1 => (self.mq & 1, 0),
                // subtract X if it is 1 (signed: the top bit)
                2 => (0, self.mq & 1),
                // non-restoring divide step
                _ if mqm == 2 => (self.s33, self.s33 ^ 1),
                // fix-up: add B if negative
                _ => (self.s33, 0),
            };
            gs = g;
            let s = (ga << 3) | (gs << 2) | (gs << 1) | ga;
            if chk && (f.m != 0 || cin != gs) {
                return self.err("step with M set or the wrong carry in");
            }
            (s, f.m as u32)
        } else {
            (f.s as u32, f.m as u32)
        };
        let uses_a = !(m == 1 && matches!(s, 0b1010 | 0b0011 | 0b1100 | 0b0101));
        let uses_b = !((m == 1 && matches!(s, 0b1111 | 0b0000 | 0b0011 | 0b1100))
            || (m == 0 && matches!(s, 0b0000 | 0b1111 | 0b1100)));
        let (fv_, c32) = alu32(av, b, s, m, cin);
        let s0 = s & 1;
        // V = (A31 ^ (B31 ^ S0)) & (A31 ^ F31): S0 tells adding from subtracting
        let vt2 = ((av >> 31) ^ (b >> 31) ^ s0) & 1;
        let ovf = vt2 & ((av >> 31) ^ (fv_ >> 31)) & 1;
        let alu_ok = (a.is_some() || !uses_a) && (bfull || !uses_b);

        // result multiplexer
        let mut res = match f.rms {
            0 => fv_,
            1 => {
                // 74HCT151: SIN field, plus 4 in multiply steps (MD = x01)
                let mulstep = (mqm == 1) as u8;
                let sign = if vt2 != 0 {
                    (av >> 31) & 1
                } else {
                    (fv_ >> 31) & 1
                };
                let sin = match f.sin | mulstep << 2 {
                    0 => 0,
                    1 => fv_ >> 31,
                    2 => self.c,
                    3 => fv_ & 1,
                    4 => c32,
                    5 => sign,
                    _ => 0,
                };
                (fv_ >> 1) | sin << 31
            }
            2 => fv_.rotate_right(8),
            _ => fv_.rotate_right(16),
        };
        for k in 0..4 {
            if f.rz >> k & 1 != 0 {
                res &= !(0xFF << (8 * k));
            }
        }

        // memory and the data bus
        let (addr, io) = if f.addrmar != 0 {
            (
                mar | if f.hiword != 0 { 2 } else { 0 },
                (mar >> 31) & 1 != 0,
            )
        } else {
            (pc, false)
        };
        let size = f.size;
        let fault = f.addrmar != 0
            && (f.memrd != 0 || f.memwr != 0)
            && ((size == 3 && mar & 3 != 0) || (size == 2 && mar & 1 != 0));
        let mut d: Option<u32> = None;
        if f.memrd != 0 {
            d = Some(bus.read(addr, io, fault, f.addrmar == 0, self.cycles));
        }
        if f.dsrc != 0 {
            if d.is_some() {
                return self.err("data bus contention");
            }
            if chk && !alu_ok {
                return self.err("store data from a floating bus");
            }
            d = Some(match f.dsrc {
                3 => res & 0xFFFF,
                2 => res >> 16,
                _ => (res & 0xFF) * 0x101,
            });
        }

        // sequencer
        let seq = f.seq;
        let y: u32 = if fault {
            0
        } else {
            match seq {
                0 => {
                    let cnd = f.cond;
                    let cv = match cnd {
                        0 => 0,
                        1 => (self.lc == 255) as u32,
                        2 => r >> 31,
                        3 => self.cl,
                        4 | 7 => {
                            // the test before the polarity bit (cc0): the
                            // routine was chosen for this polarity
                            let cc = if f.ccb != 0 {
                                (ir >> 4) & 15
                            } else {
                                (ir >> 8) & 15
                            };
                            if chk && (cnd == 7) != (cc & 1 != 0) {
                                return self
                                    .err("condition polarity doesn't match the instruction");
                            }
                            self.bcond(cc & 14) ^ (cnd == 7) as u32
                        }
                        5 => self.mq >> 31,
                        _ => (self.lc & 15 == 15) as u32,
                    };
                    let next = f.next as u32;
                    if cnd != 0 {
                        if chk && next & 1 != 0 {
                            return self.err("branch with NEXT[0] set");
                        }
                        (next & !1) | cv
                    } else {
                        next
                    }
                }
                1 => {
                    if f.goirq == 0 && d.is_none() {
                        return self.err("decode with nothing on the data bus");
                    }
                    self.ended = true;
                    let dec = self.rom.decode[((f.goirq as usize) << 16) | d.unwrap_or(0) as usize];
                    dec & ((1 << Y_BITS) - 1)
                }
                2 => {
                    let Some(dd) = d else {
                        return self.err("dispatch with nothing on the data bus");
                    };
                    (f.next as u32 & !31) | ((dd >> 8) & 15) << 1 | (dd & 0xFF != 0) as u32
                }
                _ => return self.err("bad SEQ"),
            }
        };

        // ---- clock edge
        if f.memwr != 0 && !fault {
            let Some(dd) = d else {
                return self.err("write with nothing on the data bus");
            };
            let ln = if size == 1 {
                if addr & 1 != 0 { 2 } else { 1 }
            } else {
                3
            };
            bus.write(addr, io, dd, ln);
        }
        if f.rfwe != 0 {
            if rfa != rfb {
                return self.err("register file copies written at different addresses");
            }
            if chk && !bfull {
                return self.err("register write from a floating bus");
            }
            if rfa != 0 || f.wr0 != 0 {
                self.rf[rfa] = b;
            }
        }
        if f.ldr != 0 {
            if chk && !alu_ok {
                return self.err("R loaded from a floating bus");
            }
            self.r = res;
        }
        if f.ldmar != 0 {
            let src = if f.marsrc != 0 { a } else { Some(res) };
            let Some(src) = src.filter(|_| f.marsrc != 0 || alu_ok || !chk) else {
                return self.err("MAR loaded from a floating bus");
            };
            self.mar = src & 0x800F_FFFF;
        }
        if f.ldtl != 0 || f.ldth != 0 || f.ldx != 0 || f.ldir != 0 {
            let Some(dd) = d else {
                return self.err("a load from an empty data bus");
            };
            if f.ldtl != 0 {
                self.t = (self.t & 0xFFFF_0000) | dd;
            }
            if f.ldth != 0 {
                self.t = (self.t & 0xFFFF) | dd << 16;
            }
            if f.ldx != 0 {
                if chk && f.ldir != 0 {
                    return self.err("SX loaded without an extension parcel");
                }
                self.sx = (dd >> 12) & 15;
            }
            if f.ldir != 0 {
                self.ir = dd;
                self.sx = (dd >> 4) & 15;
                self.len = self.rom.decode[dd as usize] >> Y_BITS;
                self.fetched = Some((addr, dd));
            }
        }
        if f.ldpc != 0 {
            if chk && !alu_ok {
                return self.err("PC loaded from a floating bus");
            }
            if f.pccond == 0 || self.bcond((ir >> 8) & 15) != 0 {
                self.pc = res & !1;
            }
        } else if f.memrd != 0 && f.addrmar == 0 {
            self.pc = pc.wrapping_add(2);
        }
        if f.ldlc != 0 {
            self.lc = res & 0xFF;
        } else if f.lcinc != 0 {
            self.lc = (self.lc + 1) & 0xFF;
        }
        match mqm {
            3 => {
                if chk && !bfull {
                    return self.err("MQ loaded from a floating bus");
                }
                self.mq = b;
                self.s33 = 0;
            }
            1 => self.mq = (fv_ & 1) << 31 | self.mq >> 1,
            2 => {
                let s33 = ((r >> 31) ^ c32 ^ gs) & 1;
                self.mq = self.mq << 1 | (s33 ^ 1);
                self.s33 = s33;
            }
            _ => {}
        }
        if f.ldsgn != 0 {
            self.sgn = fill.unwrap_or(0);
        }
        if f.ldcl != 0 {
            let cls = f.clsrc;
            self.cl = match cls {
                0 => (b == 0) as u32,
                1 => c32,
                _ => {
                    let hz = (b >> if cls == 2 || cls == 4 { 16 } else { 15 } == 0) as u32;
                    if cls == 2 || cls == 3 {
                        hz
                    } else {
                        self.cl & hz
                    }
                }
            };
        }
        // flags
        if f.fnz != 0 {
            if chk && !bfull {
                return self.err("flags from a floating bus");
            }
            match f.fnz {
                1 => {
                    self.n = b >> 31;
                    self.z = (b == 0) as u32;
                }
                2 => {
                    self.n = b >> 31;
                    self.z &= (b == 0) as u32;
                }
                _ => {
                    self.n = (b >> 3) & 1;
                    self.z = (b >> 2) & 1;
                }
            }
        }
        if f.czero != 0 {
            self.c = 0;
        } else if f.fc == 1 {
            let fl = fill.unwrap_or(0);
            self.c = match f.csrc {
                0 => (b >> 1) & 1,
                1 => fv_ & 1,
                2 => (fv_ >> 7) & 1,
                3 => (fv_ >> 8) & 1,
                4 => (fv_ >> 15) & 1,
                5 => fv_ >> 31,
                6 => ((fv_ >> 7) ^ fl) & 1,
                _ => ((fv_ >> 15) ^ fl) & 1,
            };
        } else if f.fc == 2 {
            self.c = c32;
        } else if f.fc == 3 {
            self.c = self.cl ^ 1;
        }
        match f.fv {
            7 => self.v = ovf,
            2 => self.v = 0,
            3 => self.v = b & 1,
            4 => self.v = self.cl ^ 1,
            5 => self.v = 1,
            _ => {}
        }
        match f.fi {
            1 => self.i = 1,
            2 => self.i = 0,
            3 => self.i = (b >> 4) & 1,
            _ => {}
        }
        // interrupt request: synchronise, then pending = request & I (next)
        let irqp = self.irqp;
        self.irqp = self.irqs & self.i;
        self.irqs = bus.irq();
        bus.tick();

        if f.halt != 0 && (self.i == 0 || !bus.timer_on()) {
            self.halted = true;
        }
        self.uaddr = irqp << IRQP_BIT | y;
        if fault {
            self.uaddr |= fault_page(self.len);
        }
        self.total += 1;
        if self.started {
            self.cycles += 1;
        } else if seq == 1 && f.ldir != 0 {
            // the reset routine fetched address 0
            self.started = true;
        }
        Ok(())
    }
}

/// The whole machine of rtl.py: the processor and its RAM and devices,
/// with the hardware's cycles per instruction address (from one opcode
/// fetch to the next).
pub struct System {
    pub cpu: Rtl,
    pub ram: Ram,
    pub pc_cycles: std::collections::HashMap<u32, u64>,
    last_fetch: Option<(u64, u32)>,
}

impl System {
    pub fn new(rom: Arc<Rom>, image: &[u8], inp: &[u8]) -> System {
        System {
            cpu: Rtl::new(rom),
            ram: Ram::new(image, inp),
            pc_cycles: Default::default(),
            last_fetch: None,
        }
    }

    pub fn step(&mut self) -> Result<(), String> {
        let started = self.cpu.started;
        let cycle = self.cpu.cycles;
        self.cpu.step(&mut self.ram)?;
        if let (true, Some((addr, _))) = (started, self.cpu.fetched) {
            if let Some((c0, a0)) = self.last_fetch {
                *self.pc_cycles.entry(a0).or_default() += cycle - c0;
            }
            self.last_fetch = Some((cycle, addr));
        }
        Ok(())
    }

    /// Run until HALT (or more than `max_cycles` cycles, an error).
    pub fn run(&mut self, max_cycles: u64) -> Result<(), String> {
        while !self.cpu.halted {
            self.step()?;
            if self.cpu.cycles > max_cycles {
                return Err(format!("cycle limit reached at PC {:08X}", self.cpu.pc));
            }
        }
        // the last instruction runs to the end
        if let Some((c0, a0)) = self.last_fetch.take() {
            *self.pc_cycles.entry(a0).or_default() += self.cpu.cycles - c0;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alu_adds_and_subtracts() {
        // add: M = 0, S = 1001, carry in 0
        assert_eq!(alu32(5, 7, 0b1001, 0, 0), (12, 0));
        assert_eq!(alu32(0xFFFF_FFFF, 1, 0b1001, 0, 0), (0, 1));
        // subtract: S = 0110 with carry in 1 (true carries: no borrow = 1)
        assert_eq!(alu32(7, 5, 0b0110, 0, 1), (2, 1));
        assert_eq!(alu32(5, 7, 0b0110, 0, 1).0, (-2i32) as u32);
        // logic: and, or, xor
        assert_eq!(alu32(0b1100, 0b1010, 0b1011, 1, 0).0, 0b1000);
        assert_eq!(alu32(0b1100, 0b1010, 0b1110, 1, 0).0, 0b1110);
        assert_eq!(alu32(0b1100, 0b1010, 0b0110, 1, 0).0, 0b0110);
    }

    #[test]
    fn io_page_halves() {
        let mut d = IoDev::default();
        d.write(0x08, 100, 3);
        d.write(0x0A, 1, 3);
        assert_eq!(d.read(0x08, 0), 100);
        assert_eq!(d.read(0x0A, 0), 1);
        assert_eq!(d.read(0x10, 0x12345), 0x2345);
        assert_eq!(d.read(0x12, 0), 1);
        assert_eq!(d.read(0x00, 0), 0xFFFF);
        assert_eq!(d.read(0x02, 0), 0xFFFF);
    }
}
