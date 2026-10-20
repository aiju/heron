//! The control store, as the engine runs it: every word's fields decoded
//! into what they do, from an image that Python writes
//! (studies/chibi/sim.py, `store_image`).
//!
//! The image names what each field does, not how ucode2.py encodes it:
//! the flag operations' and the ALU's codes were chosen by annealing and
//! may change again, and Python translates them by name. The enums here
//! are that vocabulary; sim.py lists them in the same order.
//!
//! The image, little-endian:
//!
//! | Bytes | |
//! |---|---|
//! | 4 | `CHST` |
//! | 2, 2 | the version (1), the words (8192) |
//! | 2 × 6 | the decode's base (0x100), the tasks' (0x1F80), the device task's entry, the copper's, JT's no-check bit (0x1000), 0 |
//! | 32 × 2 × 3 | each ALU code's (S, M, carry in), with ST clear and with ST set |
//! | 32 × 256 × 3 × 2 | each immediate format's halves for each register byte (d, s): the low half, the high half with ST clear and with ST set |
//! | 8192 × 32 | the words ([`Word::from_bytes`]) |

pub const WORDS: usize = 8192;
const MAGIC: &[u8; 4] = b"CHST";
const VERSION: u16 = 1;
const WORD_BYTES: usize = 32;

macro_rules! vocabulary {
    ($(#[$m:meta])* $name:ident { $($v:ident),* $(,)? }) => {
        $(#[$m])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        pub enum $name { $($v),* }

        impl $name {
            const ALL: &'static [$name] = &[$($name::$v),*];

            fn from_u8(v: u8, field: &str) -> Result<$name, String> {
                Self::ALL
                    .get(v as usize)
                    .copied()
                    .ok_or_else(|| format!("{field}: {v} isn't a {}", stringify!($name)))
            }
        }
    };
}

vocabulary!(
    /// D's source.
    Ds { None, Rf, Mem, Imm, Adr, Pch, Flw }
);
vocabulary!(
    /// The memory operation.
    Mop { None, Rdm, Wrm, Rdp, Fetch, Pcs, Ldirm }
);
vocabulary!(Axp { None, Lo, Hi });
vocabulary!(Axm { None, Lo, Hi, Inc });
vocabulary!(
    /// The register byte's change.
    Irn { None, IncD, DecS, Idx }
);
vocabulary!(Seq {
    Jump,
    Mw,
    End,
    JumpT
});
vocabulary!(
    /// The high half's variant.
    Hx { Nat, Zero, Fill, ImmH }
);
vocabulary!(
    /// The result: as is, shifted right, a byte zero- or sign-extended.
    Rm { Pass, Shr, Zxb, Sxb }
);
vocabulary!(
    /// The bit into bit 15 of a right shift.
    Si { Zero, C, D15, Co }
);
vocabulary!(
    /// The ALU's carry in, in a low half.
    Carry { Zero, One, C, Ic }
);
vocabulary!(
    /// Where a register's number comes from: K, d or s.
    Sel { K, D, S }
);
vocabulary!(
    /// The flag operations, ucode2.FLOPS's names, then the high halves'
    /// own (FL_HIGH's).
    Flop {
        None, AddLo, SubLo, AdcLo, SbcLo, IcLo, IcLoZ, LogLo, Nz16, Shr, Shl, Stn, Stz, IcStz,
        Stf0, Sta4, Cnz, Vnz, Znz, Nnz, Inz, Bnz, Binz, SetI, ClrI, Entry, SetInit, Stc,
        AddHi, SubHi, LogHi, Stz32,
    }
);
vocabulary!(
    /// A jump's condition, ucode2.CONDS's names.
    Cond { True, Z, C, N, V, Hi, Lt, Le, Ic, St, Init, Irqp, Ne, A0, Odt, I }
);

impl Flop {
    /// U_SYS's flags rather than U_FLG's: they change at the cycle's end.
    pub fn is_sys(self) -> bool {
        matches!(self, Flop::Bnz | Flop::Binz | Flop::Entry | Flop::SetInit)
    }
}

/// A microinstruction, its fields as they act.
#[derive(Clone, Copy, Debug)]
pub struct Word {
    pub ds: Ds,
    pub sz: bool,
    pub imm: u8,
    pub rsel: Sel,
    pub rk: u8,
    pub hr: u8,
    pub wen: bool,
    pub wsel: Sel,
    pub wk: u8,
    pub hw: u8,
    pub aop: u8,
    pub si: Si,
    pub rm: Rm,
    pub fl: Flop,
    pub flh: Flop,
    pub ldl: bool,
    pub mop: Mop,
    pub axp: Axp,
    pub axm: Axm,
    pub irn: Irn,
    pub seq: Seq,
    pub cond: Cond,
    /// A 16-way branch's nibble: 0 d, 1 s, 2 z (CND's low bits).
    pub mw: u8,
    pub jt: u16,
    /// The low half's ticks (LEN + 1), and the high half's (0: none).
    pub len: u8,
    pub hlen: u8,
    pub hx: Hx,
    /// The stopped machine's word.
    pub halt: bool,
    /// A loop on itself that changes nothing but the time while its
    /// condition holds: HALT's wait, the stopped machine. Once it has run
    /// once, the engine may skip its repeats until something outside
    /// changes.
    pub idle: bool,
    /// The halves as the word has them ([`Half`]); the high half's is
    /// there only with HLEN.
    pub halves: [Half; 2],
}

/// A half, as its word has it: what rtl2.py's half() works out from the
/// word's fields each time, worked out once.
#[derive(Clone, Copy, Debug)]
pub struct Half {
    /// Its access: a fetch only in the last half, nothing in a variant's
    /// high half.
    pub mop: Mop,
    /// PC on the address bus (else MAR).
    pub at_pc: bool,
    /// It reads the memory.
    pub reads: bool,
    pub ds: Ds,
    pub hx: Hx,
    pub flop: Flop,
    pub axp: Axp,
    pub axm: Axm,
    /// PC moves on by 2 (a read at PC, a fetch).
    pub pc_inc: bool,
    /// The register file's half read.
    pub hr: u8,
    pub ticks: u8,
}

impl Half {
    const NONE: Half = Half {
        mop: Mop::None,
        at_pc: false,
        reads: false,
        ds: Ds::None,
        hx: Hx::Nat,
        flop: Flop::None,
        axp: Axp::None,
        axm: Axm::None,
        pc_inc: false,
        hr: 0,
        ticks: 0,
    };
}

impl Word {
    /// A word from its 32 bytes in the image: DS, SZ, IMMF, the read's
    /// select, K and half, the write's enable, select, K and half, the ALU
    /// code, SI, RM, the low and the high half's flag operation, LDL, MOP,
    /// AXP, AXM, IRN, SEQ, the condition, the branch's nibble, JT (2
    /// bytes), the halves' ticks, HX, HALT, and three bytes of 0.
    pub fn from_bytes(b: &[u8]) -> Result<Word, String> {
        let flag = |i: usize, name: &str| match b[i] {
            0 => Ok(false),
            1 => Ok(true),
            v => Err(format!("{name}: {v} isn't 0 or 1")),
        };
        let w = Word {
            ds: Ds::from_u8(b[0], "DS")?,
            sz: flag(1, "SZ")?,
            imm: b[2],
            rsel: Sel::from_u8(b[3], "the read's select")?,
            rk: b[4],
            hr: b[5],
            wen: flag(6, "the write's enable")?,
            wsel: Sel::from_u8(b[7], "the write's select")?,
            wk: b[8],
            hw: b[9],
            aop: b[10],
            si: Si::from_u8(b[11], "SISEL")?,
            rm: Rm::from_u8(b[12], "RM")?,
            fl: Flop::from_u8(b[13], "FL")?,
            flh: Flop::from_u8(b[14], "FL's high half")?,
            ldl: flag(15, "LDL")?,
            mop: Mop::from_u8(b[16], "MOP")?,
            axp: Axp::from_u8(b[17], "AXP")?,
            axm: Axm::from_u8(b[18], "AXM")?,
            irn: Irn::from_u8(b[19], "IRN")?,
            seq: Seq::from_u8(b[20], "SEQ")?,
            cond: Cond::from_u8(b[21], "CND")?,
            mw: b[22],
            jt: u16::from_le_bytes([b[23], b[24]]),
            len: b[25],
            hlen: b[26],
            hx: Hx::from_u8(b[27], "HX")?,
            halt: flag(28, "HALT")?,
            idle: false,
            halves: [Half::NONE; 2],
        };
        if w.imm >= 32 || w.aop >= 32 || w.rk >= 32 || w.wk >= 32 || w.hr > 1 || w.hw > 1 {
            return Err("a field out of range".into());
        }
        if w.jt as usize >= WORDS || w.mw > 3 || w.len == 0 || w.len > 4 || w.hlen > 3 {
            return Err("a sequencing or length field out of range".into());
        }
        Ok(w)
    }

    /// The word as the image has it (the inverse of from_bytes).
    pub fn to_bytes(&self) -> [u8; WORD_BYTES] {
        let mut b = [0u8; WORD_BYTES];
        let jt = self.jt.to_le_bytes();
        let v = [
            self.ds as u8,
            self.sz as u8,
            self.imm,
            self.rsel as u8,
            self.rk,
            self.hr,
            self.wen as u8,
            self.wsel as u8,
            self.wk,
            self.hw,
            self.aop,
            self.si as u8,
            self.rm as u8,
            self.fl as u8,
            self.flh as u8,
            self.ldl as u8,
            self.mop as u8,
            self.axp as u8,
            self.axm as u8,
            self.irn as u8,
            self.seq as u8,
            self.cond as u8,
            self.mw,
            jt[0],
            jt[1],
            self.len,
            self.hlen,
            self.hx as u8,
            self.halt as u8,
        ];
        b[..v.len()].copy_from_slice(&v);
        b
    }

    /// A word that does nothing and goes to `next`: SEQ JUMP, CND TRUE.
    pub fn nop(next: u16) -> Word {
        Word {
            ds: Ds::None,
            sz: false,
            imm: 0,
            rsel: Sel::K,
            rk: 0,
            hr: 0,
            wen: false,
            wsel: Sel::K,
            wk: 0,
            hw: 0,
            aop: 0,
            si: Si::Zero,
            rm: Rm::Pass,
            fl: Flop::None,
            flh: Flop::None,
            ldl: false,
            mop: Mop::None,
            axp: Axp::None,
            axm: Axm::None,
            irn: Irn::None,
            seq: Seq::Jump,
            cond: Cond::True,
            mw: 0,
            jt: next ^ 1,
            len: 2,
            hlen: 0,
            hx: Hx::Nat,
            halt: false,
            idle: false,
            halves: [Half::NONE; 2],
        }
    }

    /// Work out the halves.
    fn plan(&mut self) {
        let last = (self.hlen != 0) as usize;
        for h in 0..=last {
            let hx = if h == 1 { self.hx } else { Hx::Nat };
            let mut mop = self.mop;
            if h == 1 && hx != Hx::Nat && matches!(mop, Mop::Rdm | Mop::Wrm | Mop::Rdp) {
                mop = Mop::None;
            }
            if mop == Mop::Fetch && h != last {
                mop = Mop::None;
            }
            let ds = match hx {
                Hx::Zero | Hx::Fill => Ds::None,
                Hx::ImmH => Ds::Imm,
                Hx::Nat => self.ds,
            };
            let (axp, axm) = if h == 1 {
                (
                    if self.axp == Axp::Lo {
                        Axp::Hi
                    } else {
                        Axp::None
                    },
                    match self.axm {
                        Axm::Lo => Axm::Hi,
                        Axm::Inc => Axm::Inc,
                        _ => Axm::None,
                    },
                )
            } else {
                (self.axp, self.axm)
            };
            self.halves[h] = Half {
                mop,
                at_pc: matches!(mop, Mop::Rdp | Mop::Fetch | Mop::Pcs)
                    || (self.mop == Mop::Fetch && h != last),
                reads: matches!(mop, Mop::Rdp | Mop::Fetch | Mop::Rdm | Mop::Ldirm),
                ds,
                hx,
                flop: if h == 1 { self.flh } else { self.fl },
                axp,
                axm,
                pc_inc: axp == Axp::None && matches!(mop, Mop::Rdp | Mop::Fetch),
                hr: self.hr ^ h as u8,
                ticks: if h == 1 { self.hlen } else { self.len },
            };
        }
    }

    /// Whether the word at `addr` loops on itself, changing nothing but the
    /// time: no access, no write, no flags, no latch, PC, MAR or register
    /// byte change, and one of its two next addresses its own. (Its
    /// result registers and D settle in its first run.)
    fn loops_idle(&self, addr: usize) -> bool {
        self.mop == Mop::None
            && !self.wen
            && self.fl == Flop::None
            && (self.hlen == 0 || self.flh == Flop::None)
            && !self.ldl
            && self.axp == Axp::None
            && self.axm == Axm::None
            && self.irn == Irn::None
            && self.seq == Seq::Jump
            && self.cond != Cond::A0
            && (self.jt as usize == addr || (self.jt ^ 1) as usize == addr)
    }
}

/// An ALU operation: the 74F181s' S and M, and the carry in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Aop {
    pub s: u8,
    pub m: bool,
    pub carry: Carry,
    /// S0-S3 as masks of 16 bits.
    pub k: [u16; 4],
}

impl Aop {
    pub fn new(s: u8, m: bool, carry: Carry) -> Aop {
        let k = |bit: u8| if s & bit != 0 { 0xFFFF } else { 0 };
        Aop {
            s,
            m,
            carry,
            k: [k(1), k(2), k(4), k(8)],
        }
    }
}

/// The control store and the constants the sequencer needs.
#[derive(Clone)]
pub struct Store {
    pub words: Vec<Word>,
    /// [code][ST]
    pub aops: [[Aop; 2]; 32],
    /// [format × 256 + d × 16 + s]: the low half, the high half with ST
    /// clear, with ST set.
    pub imm: Vec<[u16; 3]>,
    pub entry_base: u16,
    pub task_base: u16,
    pub device_base: u16,
    pub copper_base: u16,
    pub nochk: u16,
}

impl Store {
    pub fn from_image(b: &[u8]) -> Result<Store, String> {
        let short = || "the control store's image is too short".to_string();
        if b.len() < 8 || &b[..4] != MAGIC {
            return Err("not a control store image (CHST)".into());
        }
        let u16_at = |i: usize| -> Result<u16, String> {
            b.get(i..i + 2)
                .map(|x| u16::from_le_bytes([x[0], x[1]]))
                .ok_or_else(short)
        };
        if u16_at(4)? != VERSION {
            return Err(format!(
                "the image's version is {}, not {VERSION}",
                u16_at(4)?
            ));
        }
        if u16_at(6)? as usize != WORDS {
            return Err(format!("the image has {} words, not {WORDS}", u16_at(6)?));
        }
        let mut p = 8;
        let consts: Vec<u16> = (0..6)
            .map(|i| u16_at(p + 2 * i))
            .collect::<Result<_, _>>()?;
        p += 12;
        let aop_at = |i: usize| -> Result<Aop, String> {
            let x = b.get(i..i + 3).ok_or_else(short)?;
            Ok(Aop::new(
                x[0] & 15,
                x[1] != 0,
                Carry::from_u8(x[2], "an ALU code's carry")?,
            ))
        };
        let mut aops = [[Aop::new(0, true, Carry::Zero); 2]; 32];
        for (code, a) in aops.iter_mut().enumerate() {
            for (st, x) in a.iter_mut().enumerate() {
                *x = aop_at(p + 6 * code + 3 * st)?;
            }
        }
        p += 32 * 6;
        let mut imm = Vec::with_capacity(32 * 256);
        for i in 0..32 * 256 {
            let q = p + 6 * i;
            imm.push([u16_at(q)?, u16_at(q + 2)?, u16_at(q + 4)?]);
        }
        p += 32 * 256 * 6;
        let mut words = Vec::with_capacity(WORDS);
        for a in 0..WORDS {
            let q = p + WORD_BYTES * a;
            let wb = b.get(q..q + WORD_BYTES).ok_or_else(short)?;
            words.push(Word::from_bytes(wb).map_err(|e| format!("word {a:04X}: {e}"))?);
        }
        if b.len() != p + WORD_BYTES * WORDS {
            return Err("the control store's image is too long".into());
        }
        let mut s = Store {
            words,
            aops,
            imm,
            entry_base: consts[0],
            task_base: consts[1],
            device_base: consts[2],
            copper_base: consts[3],
            nochk: consts[4],
        };
        s.prepare();
        Ok(s)
    }

    /// The image of a store (the inverse of from_image).
    pub fn to_image(&self) -> Vec<u8> {
        let mut b = Vec::new();
        b.extend_from_slice(MAGIC);
        for v in [
            VERSION,
            WORDS as u16,
            self.entry_base,
            self.task_base,
            self.device_base,
            self.copper_base,
            self.nochk,
            0,
        ] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        for a in &self.aops {
            for x in a {
                b.extend_from_slice(&[x.s, x.m as u8, x.carry as u8]);
            }
        }
        for x in &self.imm {
            for v in x {
                b.extend_from_slice(&v.to_le_bytes());
            }
        }
        for w in &self.words {
            b.extend_from_slice(&w.to_bytes());
        }
        b
    }

    /// Each word's halves and idle mark.
    fn prepare(&mut self) {
        for a in 0..WORDS {
            let w = &mut self.words[a];
            w.plan();
            w.idle = w.loops_idle(a);
        }
    }

    /// Replace a word (for tests and patches); keeps the idle marks right.
    pub fn set_word(&mut self, a: usize, w: Word) {
        self.words[a] = w;
        self.prepare();
    }

    /// An immediate's half: the low half, or the high half as ST is.
    #[inline]
    pub fn imm(&self, format: u8, d: u8, s: u8, high: bool, st: bool) -> u16 {
        let x = &self.imm[(format as usize) << 8 | (d as usize) << 4 | s as usize];
        if !high { x[0] } else { x[1 + st as usize] }
    }
}
