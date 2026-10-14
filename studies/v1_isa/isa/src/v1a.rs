//! Draft 1a's decoder: 32-bit, 16-bit parcels, load/store (isa-v1a.md and
//! studies/v1_isa/v1a.py).

use crate::insn::{self, Access, Insn, Res, sext8, sext16};
use crate::key::Ea;
use crate::machine::Machine;

const OP_SYS: u32 = 0x0;
const OP_ALU: u32 = 0x1;
const OP_UN: u32 = 0x2;
const OP_BCC: u32 = 0x3;
const OP_LD: u32 = 0x4;
const OP_ST: u32 = 0x5;
const OP_LDB: u32 = 0x6;
const OP_STB: u32 = 0x7;
const OP_ALUI: u32 = 0x8;
const OP_JCC: u32 = 0x9;
const OP_MEML: u32 = 0xA;
const OP_SH: u32 = 0xB;
const OP_MVI: u32 = 0xC;
const OP_ADDI: u32 = 0xD;
const OP_CMPI: u32 = 0xE;

/// The long memory functions (op A) 0-7: (load, size, sign-extend).
const MEM_INFO: [(bool, u8, bool); 8] = [
    (true, 4, false),
    (false, 4, false),
    (true, 1, false),
    (false, 1, false),
    (true, 2, false),
    (false, 2, false),
    (true, 1, true),
    (true, 2, true),
];

/// The instruction at pc and its length in parcels.
pub fn decode(m: &Machine, pc: u32) -> Res<(Insn, u32)> {
    let parcel = |a: u32| m.parcel(a);
    let w = parcel(pc)?;
    let op = w >> 12;
    let (d, s, f) = (((w >> 8) & 15) as u8, ((w >> 4) & 15) as u8, (w & 15) as u8);
    Ok(match op {
        OP_SYS => (insn::dec_sys(w), 1),
        OP_ALU => (Insn::AluRR { f, d, s }, 1),
        OP_UN => (insn::dec_unary(w), 1),
        OP_BCC => (insn::dec_bcc(pc, w), 1),
        OP_LD..=OP_STB => {
            // short loads and stores: [rs + o], o scaled for words
            let word = op == OP_LD || op == OP_ST;
            let acc = Access {
                load: op == OP_LD || op == OP_LDB,
                size: if word { 4 } else { 1 },
                signed: false,
                d,
                s,
                disp: if word { 4 * f as u32 } else { f as u32 },
                ea: Ea::Rd,
            };
            (Insn::Access(acc), 1)
        }
        OP_ALUI => {
            if s > 3 {
                return Ok((Insn::Illegal, 1));
            }
            let e0 = parcel(pc.wrapping_add(2))?;
            let v = match s {
                0 => sext16(e0),
                1 => e0,
                2 => e0 << 16,
                _ => e0 | parcel(pc.wrapping_add(4))? << 16,
            };
            (Insn::AluImm { f, d, v }, if s == 3 { 3 } else { 2 })
        }
        OP_JCC => {
            let n = if s <= 1 && f == 0 {
                if s == 1 { 3 } else { 2 }
            } else {
                1
            };
            (insn::dec_jcc(pc, w, &mut |a| parcel(a))?, n)
        }
        OP_MEML => dec_long(m, pc, d, s, f)?,
        OP_SH => (insn::dec_shift(w), 1),
        OP_MVI => (
            Insn::AluImm {
                f: insn::ALU_MOV,
                d,
                v: sext8(w),
            },
            1,
        ),
        OP_ADDI => (Insn::AddI { d, v: sext8(w) }, 1),
        OP_CMPI => (
            Insn::AluImm {
                f: insn::ALU_CMP,
                d,
                v: sext8(w),
            },
            1,
        ),
        _ => (Insn::Illegal, 1),
    })
}

/// Op A: loads, stores and LEA with a 16- or 32-bit displacement.
fn dec_long(m: &Machine, pc: u32, d: u8, s: u8, f: u8) -> Res<(Insn, u32)> {
    if f == 0xF {
        return Ok((Insn::Illegal, 1));
    }
    let (n, disp, fn16, ea) = if f >= 0xA {
        let disp = m.parcel(pc.wrapping_add(2))? | m.parcel(pc.wrapping_add(4))? << 16;
        let fn16 = [0, 1, 2, 3, 8][(f - 0xA) as usize];
        (3, disp, fn16, if s == 0 { Ea::Abs } else { Ea::Rd32 })
    } else {
        let disp = sext16(m.parcel(pc.wrapping_add(2))?);
        (2, disp, f, if s == 0 { Ea::Abs } else { Ea::Rd })
    };
    let nxt = pc.wrapping_add(2 * n);
    Ok(match fn16 {
        // PC-relative LEA
        9 => (
            Insn::LeaConst {
                d,
                a: nxt.wrapping_add(disp),
            },
            n,
        ),
        8 => (Insn::Lea { d, s, disp, ea }, n),
        _ => {
            let (load, size, signed) = MEM_INFO[fn16 as usize];
            (
                Insn::Access(Access {
                    load,
                    size,
                    signed,
                    d,
                    s,
                    disp,
                    ea,
                }),
                n,
            )
        }
    })
}
