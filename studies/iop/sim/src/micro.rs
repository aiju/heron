//! The microinstruction (RFC 0027, 3.3): 48 bits, six flash ROMs wide.
//!
//! RFC 0027 gives the fields and their widths; their places in the word are
//! this study's (the microassembler, `studies/iop/uasm.py`, has the same
//! table):
//!
//! | Bits | Field | |
//! |---|---|---|
//! | 0-15 | K | a constant onto R, or a branch target |
//! | 16-21 | REG | a register of the bank, or a device on T (5-3) and its register (2-0) |
//! | 22-23 | RS | R in the first half: 0 the register, 1 memory at X, 2 K, 3 T |
//! | 24-29 | ALU | S0-S3 (24-27), M stored inverted (28), the carry in (29) |
//! | 30 | WB | F written back in the second half: to memory at X if RS is 1, else to the register |
//! | 31-33 | LD | loaded from R at E2: 0 none, 1 AC, 2 X, 3 BANK, 4 AH0, 5 AH1, 6 LC, 7 CTRL |
//! | 34-35 | BUS | 0 none, 1 read, 2 write, 3 locked read (kept) |
//! | 36 | SEG | 0 AH0, 1 AH1 onto A16-A31 |
//! | 37-38 | SZ | 0 byte 0, 1 byte 1, 2 halfword, 3 word |
//! | 39-41 | T | 0 none, 1 AB <- BA, 2 AB <- F, 3 AB <- device, 4 device <- BA, 5 device <- F, 6 T <- device (for RS = 3), 7 spare |
//! | 42-43 | SEQ | 0 next, 1 to K if COND, 2 to K unless COND, 3 to F if COND, else to K |
//! | 44-46 | COND | 0 always, 1 carry, 2 F's bit 15, 3 LC not done (and count), 4 attention, 5 a doorbell, 6-7 spare (never) |
//! | 47 | TASK | kept for hardware tasks; ignored |
//!
//! M is stored inverted so that the all-zero ALU field is M = 1, S = 0000,
//! carry in 0: one of the codes that repeat a logic function (NOT A, which
//! M = 1 and carry in 1 also give), and so HOLD. That makes the all-zero
//! microinstruction do nothing at all, F and the carry included.

pub const K: (u32, u32) = (0, 16);
pub const REG: (u32, u32) = (16, 6);
pub const RS: (u32, u32) = (22, 2);
pub const ALU: (u32, u32) = (24, 6);
pub const WB: (u32, u32) = (30, 1);
pub const LD: (u32, u32) = (31, 3);
pub const BUS: (u32, u32) = (34, 2);
pub const SEG: (u32, u32) = (36, 1);
pub const SZ: (u32, u32) = (37, 2);
pub const T: (u32, u32) = (39, 3);
pub const SEQ: (u32, u32) = (42, 2);
pub const COND: (u32, u32) = (44, 3);
pub const TASK: (u32, u32) = (47, 1);

/// The microcode's size: the 16-bit microprogram counter's reach.
pub const WORDS: usize = 1 << 16;

pub const RS_REG: u8 = 0;
pub const RS_MEM: u8 = 1;
pub const RS_K: u8 = 2;
pub const RS_T: u8 = 3;

pub const LD_NONE: u8 = 0;
pub const LD_AC: u8 = 1;
pub const LD_X: u8 = 2;
pub const LD_BANK: u8 = 3;
pub const LD_AH0: u8 = 4;
pub const LD_AH1: u8 = 5;
pub const LD_LC: u8 = 6;
pub const LD_CTRL: u8 = 7;

pub const BUS_NONE: u8 = 0;
pub const BUS_READ: u8 = 1;
pub const BUS_WRITE: u8 = 2;
pub const BUS_LOCKED: u8 = 3;

pub const SZ_B0: u8 = 0;
pub const SZ_B1: u8 = 1;
pub const SZ_HALF: u8 = 2;
pub const SZ_WORD: u8 = 3;

pub const T_NONE: u8 = 0;
pub const T_AB_BA: u8 = 1;
pub const T_AB_F: u8 = 2;
pub const T_AB_DEV: u8 = 3;
pub const T_DEV_BA: u8 = 4;
pub const T_DEV_F: u8 = 5;
pub const T_FROM_DEV: u8 = 6;

pub const SEQ_NEXT: u8 = 0;
pub const SEQ_IF: u8 = 1;
pub const SEQ_UNLESS: u8 = 2;
pub const SEQ_DISPATCH: u8 = 3;

pub const COND_ALWAYS: u8 = 0;
pub const COND_CARRY: u8 = 1;
pub const COND_F15: u8 = 2;
pub const COND_LC: u8 = 3;
pub const COND_ATTN: u8 = 4;
pub const COND_BELL: u8 = 5;

/// The devices on T (RFC 0027, 3.5), by REG bits 5-3.
pub const DEV_IO: u8 = 0;
pub const DEV_SR: u8 = 1;
pub const DEV_SWAP: u8 = 2;
pub const DEV_EVENTS: u8 = 3;
pub const DEV_PAGE: u8 = 4;
pub const DEV_TTAB: u8 = 5;

/// A microinstruction, decoded.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Micro {
    pub k: u16,
    pub reg: u8,
    pub rs: u8,
    /// S0-S3.
    pub s: u8,
    pub m: bool,
    pub cin: bool,
    pub hold: bool,
    pub wb: bool,
    pub ld: u8,
    pub bus: u8,
    pub seg: u8,
    pub sz: u8,
    pub t: u8,
    pub seq: u8,
    pub cond: u8,
    pub task: bool,
}

fn field(w: u64, (shift, width): (u32, u32)) -> u64 {
    (w >> shift) & ((1 << width) - 1)
}

impl Micro {
    pub fn decode(w: u64) -> Micro {
        let alu = field(w, ALU) as u8;
        let s = alu & 15;
        let m = alu & 16 == 0;
        let cin = alu & 32 != 0;
        Micro {
            k: field(w, K) as u16,
            reg: field(w, REG) as u8,
            rs: field(w, RS) as u8,
            s,
            m,
            cin,
            hold: m && s == 0 && !cin,
            wb: field(w, WB) != 0,
            ld: field(w, LD) as u8,
            bus: field(w, BUS) as u8,
            seg: field(w, SEG) as u8,
            sz: field(w, SZ) as u8,
            t: field(w, T) as u8,
            seq: field(w, SEQ) as u8,
            cond: field(w, COND) as u8,
            task: field(w, TASK) != 0,
        }
    }

    /// The device REG names on T.
    pub fn dev(&self) -> u8 {
        self.reg >> 3
    }

    /// Whether the microinstruction uses a device on T: reads one onto R
    /// or into AB, or writes one.
    pub fn uses_dev(&self) -> bool {
        matches!(self.t, T_AB_DEV | T_DEV_BA | T_DEV_F) || (self.rs == RS_T && self.t == T_FROM_DEV)
    }

    /// An unconditional branch: SEQ 1 with COND always.
    pub fn is_goto(&self) -> bool {
        self.seq == SEQ_IF && self.cond == COND_ALWAYS
    }
}

/// The 74F181 with a 74F182, 16 bits, active-high data: F and the carry
/// out of bit 15 for S (S3-S0), M and the carry in. A is R, B is AC.
///
/// Inside, each bit works out T1 = A | (B & S0) | (!B & S1) and
/// T2 = (A & !B & S2) | (A & B & S3); arithmetic is T1 + T2 + carry in,
/// logic is NOT (T1 XOR T2). The carry out is that of T1 + T2 + carry in
/// whatever M is, as on the chip.
pub fn alu(s: u8, m: bool, cin: bool, a: u16, b: u16) -> (u16, bool) {
    let sel = |bit: u8, v: u16| if s & bit != 0 { v } else { 0 };
    let t1 = a | sel(1, b) | sel(2, !b);
    let t2 = sel(4, a & !b) | sel(8, a & b);
    let sum = t1 as u32 + t2 as u32 + cin as u32;
    let carry = sum > 0xFFFF;
    let f = if m { !(t1 ^ t2) } else { sum as u16 };
    (f, carry)
}

const RS_NAMES: [&str; 4] = ["reg", "[X]", "K", "T"];
const LD_NAMES: [&str; 8] = ["", "AC", "X", "BANK", "AH0", "AH1", "LC", "CTRL"];
const T_NAMES: [&str; 8] = [
    "", "AB<-BA", "AB<-F", "AB<-dev", "dev<-BA", "dev<-F", "T<-dev", "t7",
];
const COND_NAMES: [&str; 8] = ["always", "carry", "F15", "lc", "attn", "bell", "c6", "c7"];

/// A microinstruction's fields as text, for traces.
pub fn disassemble(w: u64) -> String {
    let u = Micro::decode(w);
    if w == 0 {
        return "nop".into();
    }
    let mut out = vec![];
    let alu = if u.hold {
        "hold".to_string()
    } else {
        format!(
            "{}s{:X}{}",
            if u.m { "L" } else { "A" },
            u.s,
            if u.cin { "+c" } else { "" }
        )
    };
    out.push(format!("{} {} r{}", RS_NAMES[u.rs as usize], alu, u.reg));
    if u.wb {
        out.push("wb".into());
    }
    if u.ld != 0 {
        out.push(format!("ld {}", LD_NAMES[u.ld as usize]));
    }
    if u.bus != 0 {
        let sz = ["b0", "b1", "h", "w"][u.sz as usize];
        let op = ["", "rd", "wr", "rdl"][u.bus as usize];
        out.push(format!("{op}.{sz} AH{}", u.seg));
    }
    if u.t != 0 {
        out.push(T_NAMES[u.t as usize].into());
    }
    match u.seq {
        SEQ_IF => out.push(format!("if {} {:04X}", COND_NAMES[u.cond as usize], u.k)),
        SEQ_UNLESS => out.push(format!(
            "unless {} {:04X}",
            COND_NAMES[u.cond as usize], u.k
        )),
        SEQ_DISPATCH => out.push(format!(
            "if {} F else {:04X}",
            COND_NAMES[u.cond as usize], u.k
        )),
        _ if u.cond == COND_LC => out.push("count".into()),
        _ => {}
    }
    if u.rs == RS_K {
        out.push(format!("K={:04X}", u.k));
    }
    out.join(" | ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alu_functions() {
        // arithmetic: A + B, A - B, A + 1, A - 1, A + A
        assert_eq!(alu(0b1001, false, false, 3, 4), (7, false));
        assert_eq!(alu(0b1001, false, false, 0xFFFF, 1), (0, true));
        assert_eq!(alu(0b0110, false, true, 5, 3), (2, true));
        assert_eq!(alu(0b0110, false, true, 3, 5), (0xFFFE, false));
        assert_eq!(alu(0b0000, false, true, 9, 0), (10, false));
        assert_eq!(alu(0b1111, false, false, 9, 0), (8, true));
        assert_eq!(alu(0b1111, false, false, 0, 0), (0xFFFF, false));
        assert_eq!(alu(0b1100, false, false, 0x4001, 0), (0x8002, false));
        // (A & B) - 1: a borrow exactly when A & B is 0
        assert_eq!(alu(0b1011, false, false, 0xFFFF, 0), (0xFFFF, false));
        assert_eq!(alu(0b1011, false, false, 0xFFFF, 5), (4, true));
        // logic
        assert_eq!(alu(0b0000, true, true, 0x00FF, 0).0, 0xFF00);
        assert_eq!(alu(0b0110, true, false, 0x0FF0, 0x00FF).0, 0x0F0F);
        assert_eq!(alu(0b1011, true, false, 0x0FF0, 0x00FF).0, 0x00F0);
        assert_eq!(alu(0b1110, true, false, 0x0FF0, 0x00FF).0, 0x0FFF);
        assert_eq!(alu(0b1010, true, false, 0x1234, 0x5678).0, 0x5678);
        assert_eq!(alu(0b1111, true, false, 0x1234, 0x5678).0, 0x1234);
        assert_eq!(alu(0b0011, true, false, 0x1234, 0x5678).0, 0);
        assert_eq!(alu(0b1100, true, false, 0x1234, 0x5678).0, 0xFFFF);
    }

    #[test]
    fn zero_is_hold() {
        let u = Micro::decode(0);
        assert!(u.hold && u.m && !u.wb && u.ld == 0 && u.bus == 0 && u.t == 0 && u.seq == 0);
        // NOT A is still there, with the carry in set
        let not_a = 1u64 << 29;
        assert!(!Micro::decode(not_a).hold);
    }
}
